"""Pure preflight for the first native BRS child.

This module validates a detached, bounded projection of a durable BRS wave.  It does not
open a ledger or workspace, inspect a file, call a callback, reserve budget, create a
staging entry, claim an episode, spawn a worker, or grant an owner/worker token.  The
selection returned by :func:`preflight_native_brs_child` is descriptive data only.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

BRS_CHILD_POLICY_PROTOCOL = "lunar-rsi-python-brs-child-preflight-v1"
BRS_CHILD_POLICY_SCHEMA_VERSION = 1
MAX_BRS_CHILD_PREFLIGHT_BYTES = 112 * 1024
MAX_BRS_CHILD_PREFLIGHT_DEPTH = 32
MAX_BRS_CHILD_ATTEMPTS = 8
MAX_BRS_CHILD_CANDIDATES = 32
MAX_BRS_CHILD_AGGREGATE_BYTES = 64 * 1024 * 1024

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
    "schema_version", "protocol", "run_id", "mode", "wave", "max_workers",
    "root_snapshot_sha256", "intents", "executions", "budget", "caps",
}
_INTENT_FIELDS = {"ordinal", "episode_id", "request_sha256"}
_BUDGET_FIELDS = {"planned", "consumed"}
_COUNTERS = (
    "practice_rounds", "target_attempts", "practice_episodes", "solver_invocations",
    "unknown_retries", "evaluator_invocations", "verifier_invocations", "transfer_invocations",
)
_CAP_FIELDS = {"attempts", "candidates", "checkpoint_bytes", "aggregate_bytes"}


class BRSChildPolicyError(RSILearningError):
    """A stable refusal code for a malformed or unsafe detached projection."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_child_policy_" + code)


def _fail(code: str) -> NoReturn:
    raise BRSChildPolicyError(code)


def _identity(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(f"{name}_invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(f"{name}_invalid")
    return value


def _integer(value: object, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        _fail(f"{name}_invalid")
    return value


def _shape(value: object, depth: int = 0) -> None:
    """Reject mutable subclasses and non-finite numbers before any serialization."""
    if depth > MAX_BRS_CHILD_PREFLIGHT_DEPTH:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind in {str, bool, int}:
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        children = value.items()
    elif kind is list:
        children = ((None, child) for child in value)
    else:
        _fail("shape_invalid")
    for key, child in children:
        if key is not None and type(key) is not str:
            _fail("shape_invalid")
        _shape(child, depth + 1)


def _decode(value: object) -> dict[str, Any]:
    if type(value) is bytes:
        if len(value) > MAX_BRS_CHILD_PREFLIGHT_BYTES:
            _fail("bytes_exceeded")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("duplicate_key")
                result[key] = item
            return result

        try:
            decoded = json.loads(
                value.decode("utf-8"), object_pairs_hook=pairs,
                parse_constant=lambda _constant: _fail("shape_invalid"),
            )
        except BRSChildPolicyError:
            raise
        except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
            raise BRSChildPolicyError("wire_invalid") from exc
        if type(decoded) is not dict:
            _fail("shape_invalid")
        _shape(decoded)
        try:
            if canonical_json(decoded, maximum=MAX_BRS_CHILD_PREFLIGHT_BYTES) != value:
                _fail("noncanonical")
        except BRSChildPolicyError:
            raise
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise BRSChildPolicyError("wire_invalid") from exc
        return decoded
    if type(value) is not dict:
        _fail("shape_invalid")
    _shape(value)
    try:
        canonical_json(value, maximum=MAX_BRS_CHILD_PREFLIGHT_BYTES)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSChildPolicyError("wire_invalid") from exc
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _budget(value: object) -> tuple[tuple[str, int | None], tuple[str, int]]:
    if type(value) is not dict or set(value) != _BUDGET_FIELDS:
        _fail("budget_shape_invalid")
    planned_raw, consumed_raw = value["planned"], value["consumed"]
    if (type(planned_raw) is not dict or type(consumed_raw) is not dict
            or set(planned_raw) != set(_COUNTERS) or set(consumed_raw) != set(_COUNTERS)):
        _fail("budget_shape_invalid")
    planned: list[tuple[str, int | None]] = []
    consumed: list[tuple[str, int]] = []
    for name in _COUNTERS:
        limit = planned_raw[name]
        if limit is not None:
            limit = _integer(limit, f"budget_{name}")
        used = _integer(consumed_raw[name], f"budget_{name}_consumed")
        if limit is not None and used > limit:
            _fail("budget_exhausted")
        planned.append((name, limit))
        consumed.append((name, used))
    return tuple(planned), tuple(consumed)


@dataclass(frozen=True, slots=True)
class BRSNativeChildSelection:
    """A detached description; ``authority`` is permanently false."""

    run_id: str
    wave: int
    ordinal: int
    episode_id: str
    request_sha256: str
    root_snapshot_sha256: str
    planned_budget: tuple[tuple[str, int | None], ...]
    consumed_budget: tuple[tuple[str, int], ...]
    authority: bool = False

    def __post_init__(self) -> None:
        _identity(self.run_id, "run_id")
        _integer(self.wave, "wave")
        _integer(self.ordinal, "ordinal", maximum=MAX_BRS_CHILD_ATTEMPTS - 1)
        _identity(self.episode_id, "episode_id")
        _digest(self.request_sha256, "request_sha256")
        _digest(self.root_snapshot_sha256, "root_snapshot_sha256")
        if (self.planned_budget != tuple(self.planned_budget)
                or self.consumed_budget != tuple(self.consumed_budget)):
            _fail("budget_invalid")
        if (tuple(name for name, _limit in self.planned_budget) != _COUNTERS
                or tuple(name for name, _used in self.consumed_budget) != _COUNTERS):
            _fail("budget_invalid")
        for (_name, limit), (_used_name, used) in zip(self.planned_budget, self.consumed_budget):
            if type(used) is not int or used < 0 or (limit is not None and (type(limit) is not int or used > limit)):
                _fail("budget_invalid")
        if self.episode_id != f"{self.run_id}-practice-{self.wave}-{self.ordinal}":
            _fail("episode_identity_invalid")
        if self.authority is not False:
            _fail("authority_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "wave": self.wave,
            "ordinal": self.ordinal,
            "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "root_snapshot_sha256": self.root_snapshot_sha256,
            "budget": {
                "planned": dict(self.planned_budget),
                "consumed": dict(self.consumed_budget),
            },
            "authority": False,
        }


@dataclass(frozen=True, slots=True)
class BRSNativeChildPreflight:
    """Validated detached wave state with no ledger, process or owner capability."""

    run_id: str
    wave: int
    root_snapshot_sha256: str
    intents: tuple[tuple[int, str, str], ...]
    executions: tuple[str, ...]
    planned_budget: tuple[tuple[str, int | None], ...]
    consumed_budget: tuple[tuple[str, int], ...]
    attempts: int
    candidates: int
    checkpoint_bytes: int
    aggregate_bytes: int
    max_workers: int = 1

    @classmethod
    def from_wire(cls, value: object) -> BRSNativeChildPreflight:
        raw = _decode(value)
        if set(raw) != _FIELDS:
            _fail("fields_invalid")
        if raw["schema_version"] != BRS_CHILD_POLICY_SCHEMA_VERSION:
            _fail("schema_invalid")
        if raw["protocol"] != BRS_CHILD_POLICY_PROTOCOL:
            _fail("protocol_invalid")
        run_id = _identity(raw["run_id"], "run_id")
        if raw["mode"] != "brs":
            _fail("mode_invalid")
        wave = _integer(raw["wave"], "wave", maximum=MAX_BRS_CHILD_ATTEMPTS - 1)
        if raw["max_workers"] != 1:
            _fail("max_workers_invalid")
        root = _digest(raw["root_snapshot_sha256"], "root_snapshot_sha256")
        intent_raw = raw["intents"]
        if type(intent_raw) is not list or not 1 <= len(intent_raw) <= MAX_BRS_CHILD_ATTEMPTS:
            _fail("intents_invalid")
        intents: list[tuple[int, str, str]] = []
        for ordinal, item in enumerate(intent_raw):
            if type(item) is not dict or set(item) != _INTENT_FIELDS:
                _fail("intent_shape_invalid")
            if item["ordinal"] != ordinal:
                _fail("ordinal_invalid")
            episode_id = _identity(item["episode_id"], "episode_id")
            if episode_id != f"{run_id}-practice-{wave}-{ordinal}":
                _fail("episode_identity_invalid")
            request = _digest(item["request_sha256"], "request_sha256")
            intents.append((ordinal, episode_id, request))
        execution_raw = raw["executions"]
        if type(execution_raw) is not list:
            _fail("executions_invalid")
        intent_ids = tuple(item[1] for item in intents)
        if len(execution_raw) > len(intent_ids):
            _fail("executions_invalid")
        executions = tuple(_identity(item, "execution_id") for item in execution_raw)
        if len(set(executions)) != len(executions) or any(item not in intent_ids for item in executions):
            _fail("execution_identity_invalid")
        if executions != tuple(item for item in intent_ids if item in executions):
            _fail("execution_order_invalid")
        planned, consumed = _budget(raw["budget"])
        planned_map, consumed_map = dict(planned), dict(consumed)
        for name in ("practice_episodes", "solver_invocations"):
            limit = planned_map[name]
            if limit is not None and limit < len(intent_ids):
                _fail("budget_wave_exceeds_limit")
        if consumed_map["practice_episodes"] < len(executions):
            _fail("budget_consumed_mismatch")
        if consumed_map["solver_invocations"] < len(executions):
            _fail("budget_consumed_mismatch")
        caps = raw["caps"]
        if type(caps) is not dict or set(caps) != _CAP_FIELDS:
            _fail("caps_shape_invalid")
        attempts = _integer(caps["attempts"], "attempts", maximum=MAX_BRS_CHILD_ATTEMPTS)
        candidates = _integer(caps["candidates"], "candidates", maximum=MAX_BRS_CHILD_CANDIDATES)
        checkpoint = _integer(caps["checkpoint_bytes"], "checkpoint_bytes", maximum=MAX_BRS_CHILD_PREFLIGHT_BYTES)
        aggregate = _integer(caps["aggregate_bytes"], "aggregate_bytes", maximum=MAX_BRS_CHILD_AGGREGATE_BYTES)
        if attempts < len(executions):
            _fail("attempts_mismatch")
        return cls(run_id, wave, root, tuple(intents), executions, planned, consumed,
                   attempts, candidates, checkpoint, aggregate)

    def select_next_pending(self) -> BRSNativeChildSelection | None:
        completed = set(self.executions)
        for ordinal, episode_id, request in self.intents:
            if episode_id not in completed:
                return BRSNativeChildSelection(
                    self.run_id, self.wave, ordinal, episode_id, request,
                    self.root_snapshot_sha256, self.planned_budget, self.consumed_budget,
                )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BRS_CHILD_POLICY_SCHEMA_VERSION,
            "protocol": BRS_CHILD_POLICY_PROTOCOL,
            "run_id": self.run_id,
            "mode": "brs",
            "wave": self.wave,
            "max_workers": self.max_workers,
            "root_snapshot_sha256": self.root_snapshot_sha256,
            "intents": [
                {"ordinal": ordinal, "episode_id": episode_id, "request_sha256": request}
                for ordinal, episode_id, request in self.intents
            ],
            "executions": list(self.executions),
            "budget": {"planned": dict(self.planned_budget), "consumed": dict(self.consumed_budget)},
            "caps": {
                "attempts": self.attempts,
                "candidates": self.candidates,
                "checkpoint_bytes": self.checkpoint_bytes,
                "aggregate_bytes": self.aggregate_bytes,
            },
        }


def preflight_native_brs_child(value: object) -> BRSNativeChildPreflight:
    """Validate a detached BRS projection without creating any execution authority."""
    return BRSNativeChildPreflight.from_wire(value)


__all__ = [
    "BRS_CHILD_POLICY_PROTOCOL",
    "BRS_CHILD_POLICY_SCHEMA_VERSION",
    "MAX_BRS_CHILD_AGGREGATE_BYTES",
    "MAX_BRS_CHILD_ATTEMPTS",
    "MAX_BRS_CHILD_CANDIDATES",
    "MAX_BRS_CHILD_PREFLIGHT_BYTES",
    "MAX_BRS_CHILD_PREFLIGHT_DEPTH",
    "BRSChildPolicyError",
    "BRSNativeChildPreflight",
    "BRSNativeChildSelection",
    "preflight_native_brs_child",
]
