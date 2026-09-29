"""Durable DTOs for the optional automatic-solve/WorkerService bridge.

This module intentionally contains no execution logic.  A binding is an append-only ownership
record for one automatic Run and one WorkerService attempt; native execution remains owned by the
automatic-solve lifecycle.  Store methods use the generation field as a small compare-and-swap
fence so a late worker cannot overwrite a resumed generation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AutomaticSolveWorkerBindingState(StrEnum):
    ADMITTED = "admitted"
    ACTIVE = "active"
    AWAITING_INPUT = "awaiting_input"
    RECOVERY_REQUIRED = "recovery_required"
    UNKNOWN = "unknown"
    SUPERSEDED = "superseded"
    TERMINAL = "terminal"


_SHA256 = set("0123456789abcdef")
_MAX_TEXT = 512
_MAX_POLICY = 16 * 1024


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()) or "\x00" in value:
        raise ValueError(f"invalid {name}")
    if len(value.encode("utf-8")) > _MAX_TEXT:
        raise ValueError(f"{name} is too large")
    return value


def _digest(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or len(value) != 64 or any(char not in _SHA256 for char in value):
        raise ValueError(f"invalid {name}")
    return value


def _policy(value: object) -> str:
    if isinstance(value, str):
        raw = value
    elif isinstance(value, dict):
        try:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid budget policy") from exc
    else:
        raise TypeError("invalid budget policy")
    if not raw or len(raw.encode("utf-8")) > _MAX_POLICY:
        raise ValueError("invalid budget policy")
    def reject_duplicates(pairs):
        parsed = {}
        for key, item in pairs:
            if key in parsed:
                raise ValueError("duplicate budget policy key")
            parsed[key] = item
        return parsed
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid budget policy")),
        )
        if not isinstance(parsed, dict):
            raise TypeError("invalid budget policy")
        raw = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid budget policy") from exc
    return raw


@dataclass(frozen=True, slots=True)
class AutomaticSolveWorkerBinding:
    binding_id: str
    owner_id: str
    run_id: str
    workspace_identity: str
    worker_id: str
    worker_attempt_id: str
    service_owner_id: str
    generation: int = 0
    state: AutomaticSolveWorkerBindingState = AutomaticSolveWorkerBindingState.ADMITTED
    lifecycle_digest: str = ""
    runtime_fingerprint: str = ""
    budget_policy: str | dict[str, Any] = "{}"
    contract_digest: str | None = None
    child_run_id: str | None = None
    prior_generation: int | None = None
    observation_reason: str | None = None
    stop_reason: str | None = None
    result_ref_digest: str | None = None
    native_receipt_id: str | None = None
    delivery_identity: str | None = None
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("invalid automatic solve binding schema version")
        for value, name in (
            (self.binding_id, "binding_id"), (self.owner_id, "owner_id"), (self.run_id, "run_id"),
            (self.workspace_identity, "workspace_identity"), (self.worker_id, "worker_id"),
            (self.worker_attempt_id, "worker_attempt_id"), (self.service_owner_id, "service_owner_id"),
        ):
            _text(value, name)
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("invalid generation")
        if self.prior_generation is not None and (
            isinstance(self.prior_generation, bool) or not isinstance(self.prior_generation, int)
            or self.prior_generation < 0 or self.prior_generation >= self.generation
        ):
            raise ValueError("invalid prior generation")
        if not isinstance(self.state, AutomaticSolveWorkerBindingState):
            try:
                object.__setattr__(self, "state", AutomaticSolveWorkerBindingState(self.state))
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid binding state") from exc
        _digest(self.lifecycle_digest, "lifecycle_digest")
        _digest(self.runtime_fingerprint, "runtime_fingerprint")
        _digest(self.contract_digest, "contract_digest", optional=True)
        object.__setattr__(self, "budget_policy", _policy(self.budget_policy))
        for value, name in ((self.child_run_id, "child_run_id"), (self.observation_reason, "observation_reason"),
                            (self.stop_reason, "stop_reason"), (self.native_receipt_id, "native_receipt_id"),
                            (self.delivery_identity, "delivery_identity")):
            if value is not None:
                _text(value, name)
        _digest(self.result_ref_digest, "result_ref_digest", optional=True)

    def normalized_policy(self) -> str:
        return _policy(self.budget_policy)

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id, "owner_id": self.owner_id, "run_id": self.run_id,
            "workspace_identity": self.workspace_identity, "worker_id": self.worker_id,
            "worker_attempt_id": self.worker_attempt_id, "service_owner_id": self.service_owner_id,
            "generation": self.generation, "state": self.state.value,
            "lifecycle_digest": self.lifecycle_digest, "runtime_fingerprint": self.runtime_fingerprint,
            "budget_policy": self.normalized_policy(), "contract_digest": self.contract_digest,
            "child_run_id": self.child_run_id, "prior_generation": self.prior_generation,
            "observation_reason": self.observation_reason, "stop_reason": self.stop_reason,
            "result_ref_digest": self.result_ref_digest, "native_receipt_id": self.native_receipt_id,
            "delivery_identity": self.delivery_identity, "created_at": self.created_at,
            "updated_at": self.updated_at, "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AutomaticSolveWorkerResultReference:
    binding_id: str
    generation: int
    run_id: str
    worker_attempt_id: str
    outcome: str
    reference: dict[str, object]
    sha256: str = ""
    created_at: str = ""
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("invalid automatic solve result schema version")
        _text(self.binding_id, "binding_id")
        _text(self.run_id, "run_id")
        _text(self.worker_attempt_id, "worker_attempt_id")
        if self.outcome not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("invalid result outcome")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("invalid generation")
        if type(self.reference) is not dict or not self.reference:
            raise ValueError("invalid result reference")
        try:
            payload = {
                "schema_version": self.schema_version,
                "binding_id": self.binding_id,
                "generation": self.generation,
                "run_id": self.run_id,
                "worker_attempt_id": self.worker_attempt_id,
                "outcome": self.outcome,
                "reference": self.reference,
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid result reference") from exc
        if len(encoded) > _MAX_POLICY:
            raise ValueError("result reference is too large")
        digest = hashlib.sha256(encoded).hexdigest()
        if self.sha256 and self.sha256 != digest:
            raise ValueError("result reference digest mismatch")
        object.__setattr__(self, "sha256", digest)
        # Copy the supplied JSON so later caller mutations cannot rewrite a DTO after validation.
        object.__setattr__(self, "reference", json.loads(encoded)["reference"])

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id, "generation": self.generation, "run_id": self.run_id,
            "worker_attempt_id": self.worker_attempt_id, "outcome": self.outcome,
            "reference": self.reference, "sha256": self.sha256, "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


def binding_payload_equal(left: AutomaticSolveWorkerBinding, right: AutomaticSolveWorkerBinding) -> bool:
    """Compare immutable admission identity for create-only idempotency."""
    keys = ("binding_id", "owner_id", "run_id", "workspace_identity", "worker_id", "worker_attempt_id",
            "service_owner_id", "generation", "lifecycle_digest", "runtime_fingerprint", "contract_digest",
            "child_run_id", "prior_generation", "budget_policy")
    return all(getattr(left, key) == getattr(right, key) for key in keys)
