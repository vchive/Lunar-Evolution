"""Immutable RSI run fingerprints and fail-closed compatibility checks.

The RSI controller stores one :class:`RSIFingerprintContract` with each run.  The contract is a
small, content-addressed description of every identity which can change the meaning of a receipt:
problem contract, evaluator, environment, frozen memory, solver settings, actor, verifier,
curriculum and target judge.  It deliberately does not inspect those components or execute code;
callers provide already computed digests.

Fingerprints are compared as an all-or-nothing set.  A missing, malformed or changed identity is
reported as drift and can never be silently treated as compatible.  This module is provider-free
and does not modify the RSI controller or its store.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, NamedTuple

from .candidate_evaluation_spec import canonical_json, strict_json

RSI_FINGERPRINT_SCHEMA_VERSION = "1"
RSI_FINGERPRINT_KIND = "rsi_run_fingerprint"
MAX_FINGERPRINT_RECORD_BYTES = 128 * 1024
MAX_SOLVER_SETTING_KEYS = 64
MAX_SOLVER_SETTING_DEPTH = 8
MAX_SOLVER_SETTING_TEXT_BYTES = 8 * 1024


class _FrozenObject(tuple):
    """Immutable JSON object representation that cannot be confused with an array."""


class _FrozenArray(tuple):
    """Immutable JSON array representation."""


class RSIFingerprintError(ValueError):
    """A bounded, stable failure raised for invalid or incompatible fingerprints."""

    _CODES: ClassVar[frozenset[str]] = frozenset({
        "invalid",
        "missing",
        "digest_invalid",
        "solver_id_invalid",
        "solver_settings_invalid",
        "record_invalid",
        "record_too_large",
        "drift",
        "expected_invalid",
        "actual_invalid",
    })

    def __init__(self, code: str, *, reasons: Sequence[str] = ()) -> None:
        normalized = code if code in self._CODES else "invalid"
        self.code = f"rsi_fingerprint_{normalized}"
        self.reasons = tuple(reasons)
        suffix = ":" + ",".join(self.reasons) if self.reasons else ""
        super().__init__(self.code + suffix)


def _fail(code: str) -> None:
    raise RSIFingerprintError(code)


def _digest(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise RSIFingerprintError("digest_invalid", reasons=(field,))
    return value


def _text(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise RSIFingerprintError("solver_id_invalid", reasons=(field,))
    if any(char in value for char in "\r\n"):
        raise RSIFingerprintError("solver_id_invalid", reasons=(field,))
    try:
        if len(value.encode("utf-8")) > MAX_SOLVER_SETTING_TEXT_BYTES:
            raise RSIFingerprintError("solver_id_invalid", reasons=(field,))
    except UnicodeEncodeError as exc:
        raise RSIFingerprintError("solver_id_invalid", reasons=(field,)) from exc
    return value


def _normalize_json(value: object, *, depth: int = 0, field: str = "solver_settings") -> Any:
    """Normalize a bounded JSON value into immutable, canonical-friendly containers."""

    if depth > MAX_SOLVER_SETTING_DEPTH:
        raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
    if value is None or type(value) is bool or type(value) is str:
        if type(value) is str:
            try:
                if len(value.encode("utf-8")) > MAX_SOLVER_SETTING_TEXT_BYTES or "\x00" in value:
                    raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
            except UnicodeEncodeError as exc:
                raise RSIFingerprintError("solver_settings_invalid", reasons=(field,)) from exc
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_SOLVER_SETTING_KEYS:
            raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
        items: list[tuple[str, Any]] = []
        for key, item in value.items():
            if type(key) is not str or not key or "\x00" in key or "\r" in key or "\n" in key:
                raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
            items.append((key, _normalize_json(item, depth=depth + 1, field=field)))
        return _FrozenObject(sorted(items, key=lambda pair: pair[0]))
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_SOLVER_SETTING_KEYS:
            raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))
        return _FrozenArray(_normalize_json(item, depth=depth + 1, field=field) for item in value)
    raise RSIFingerprintError("solver_settings_invalid", reasons=(field,))


def _json_value(value: Any) -> Any:
    if isinstance(value, _FrozenObject):
        return {item[0]: _json_value(item[1]) for item in value}
    if isinstance(value, (_FrozenArray, tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _settings(value: object) -> tuple[tuple[str, Any], ...]:
    normalized = value if isinstance(value, _FrozenObject) else _normalize_json(value)
    if not isinstance(normalized, _FrozenObject) or any(
        not isinstance(item, tuple) or len(item) != 2 or type(item[0]) is not str
        for item in normalized
    ):
        raise RSIFingerprintError("solver_settings_invalid", reasons=("solver_settings",))
    return normalized


@dataclass(frozen=True)
class RSIFingerprintContract:
    """The immutable identity contract for one RSI run or resumable episode."""

    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str
    solver_id: str
    solver_settings: tuple[tuple[str, Any], ...]
    actor_fingerprint: str
    verifier_fingerprint: str
    curriculum_fingerprint: str
    target_judge_fingerprint: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.contract_sha256, "contract_sha256"),
            (self.evaluator_sha256, "evaluator_sha256"),
            (self.environment_sha256, "environment_sha256"),
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.actor_fingerprint, "actor_fingerprint"),
            (self.verifier_fingerprint, "verifier_fingerprint"),
            (self.curriculum_fingerprint, "curriculum_fingerprint"),
            (self.target_judge_fingerprint, "target_judge_fingerprint"),
        ):
            _digest(value, field=field)
        _text(self.solver_id, field="solver_id")
        object.__setattr__(self, "solver_settings", _settings(self.solver_settings))
        # Force canonical serialization at construction time.  This catches unsupported values,
        # duplicate/non-string map keys and oversized records before they reach a ledger.
        try:
            payload = self.to_dict()
            encoded = canonical_json(payload, maximum=MAX_FINGERPRINT_RECORD_BYTES)
        except RSIFingerprintError:
            raise
        except Exception as exc:  # pragma: no cover - defensive trust-boundary conversion
            raise RSIFingerprintError("record_invalid") from exc
        if len(encoded) > MAX_FINGERPRINT_RECORD_BYTES:
            raise RSIFingerprintError("record_too_large")

    @classmethod
    def build(
        cls,
        *,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        memory_snapshot_sha256: str,
        solver_id: str,
        solver_settings: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        actor_fingerprint: str,
        verifier_fingerprint: str,
        curriculum_fingerprint: str,
        target_judge_fingerprint: str,
        target_judge_sha256: str | None = None,
    ) -> RSIFingerprintContract:
        """Build a contract while accepting a mapping for ergonomic call sites.

        ``target_judge_sha256`` is a compatibility alias for callers that use the data-model's
        ``*_sha256`` naming.  Supplying both aliases with different values fails closed.
        """

        if target_judge_sha256 is not None:
            if target_judge_fingerprint != target_judge_sha256:
                raise RSIFingerprintError("record_invalid", reasons=("target_judge",))
            target_judge_fingerprint = target_judge_sha256
        return cls(
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            memory_snapshot_sha256=memory_snapshot_sha256,
            solver_id=solver_id,
            solver_settings=_settings({} if solver_settings is None else solver_settings),
            actor_fingerprint=actor_fingerprint,
            verifier_fingerprint=verifier_fingerprint,
            curriculum_fingerprint=curriculum_fingerprint,
            target_judge_fingerprint=target_judge_fingerprint,
        )

    @classmethod
    def from_dict(cls, value: object) -> RSIFingerprintContract:
        if not isinstance(value, Mapping):
            raise RSIFingerprintError("record_invalid")
        expected = {
            "schema_version", "kind", "contract_sha256", "evaluator_sha256", "environment_sha256",
            "memory_snapshot_sha256", "solver_id", "solver_settings", "actor_fingerprint",
            "verifier_fingerprint", "curriculum_fingerprint", "target_judge_fingerprint",
        }
        if set(value) != expected or value.get("schema_version") != RSI_FINGERPRINT_SCHEMA_VERSION or value.get("kind") != RSI_FINGERPRINT_KIND:
            raise RSIFingerprintError("record_invalid")
        try:
            encoded = canonical_json(dict(value), maximum=MAX_FINGERPRINT_RECORD_BYTES)
            decoded = strict_json(encoded, maximum=MAX_FINGERPRINT_RECORD_BYTES)
        except Exception as exc:
            if isinstance(exc, RSIFingerprintError):
                raise
            raise RSIFingerprintError("record_invalid") from exc
        if decoded != dict(value):
            raise RSIFingerprintError("record_invalid")
        return cls.build(
            contract_sha256=value["contract_sha256"],
            evaluator_sha256=value["evaluator_sha256"],
            environment_sha256=value["environment_sha256"],
            memory_snapshot_sha256=value["memory_snapshot_sha256"],
            solver_id=value["solver_id"],
            solver_settings=value["solver_settings"],
            actor_fingerprint=value["actor_fingerprint"],
            verifier_fingerprint=value["verifier_fingerprint"],
            curriculum_fingerprint=value["curriculum_fingerprint"],
            target_judge_fingerprint=value["target_judge_fingerprint"],
        )

    @property
    def target_judge_sha256(self) -> str:
        """Compatibility alias for data-model prose using SHA-256 suffixes."""

        return self.target_judge_fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RSI_FINGERPRINT_SCHEMA_VERSION,
            "kind": RSI_FINGERPRINT_KIND,
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
            "solver_id": self.solver_id,
            "solver_settings": _json_value(self.solver_settings),
            "actor_fingerprint": self.actor_fingerprint,
            "verifier_fingerprint": self.verifier_fingerprint,
            "curriculum_fingerprint": self.curriculum_fingerprint,
            "target_judge_fingerprint": self.target_judge_fingerprint,
        }

    def digest(self) -> str:
        """Return the canonical SHA-256 digest of the complete contract."""

        return hashlib.sha256(
            canonical_json(self.to_dict(), maximum=MAX_FINGERPRINT_RECORD_BYTES)
        ).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Readable alias for :meth:`digest`."""

        return self.digest()


# Names used by early RSI design notes and external fixtures.
RunFingerprint = RSIFingerprintContract
FingerprintContract = RSIFingerprintContract


class FingerprintDriftReason(NamedTuple):
    """One deterministic reason why two otherwise valid contracts differ."""

    field: str
    expected: object
    actual: object

    @property
    def code(self) -> str:
        return f"{self.field}_changed"

    def to_dict(self) -> dict[str, object]:
        return {"field": self.field, "code": self.code, "expected": _json_value(self.expected), "actual": _json_value(self.actual)}


@dataclass(frozen=True)
class FingerprintComparison:
    """Result of comparing two run fingerprint contracts."""

    compatible: bool
    drift_reasons: tuple[FingerprintDriftReason, ...] = ()

    @property
    def drifted(self) -> bool:
        return not self.compatible

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in self.drift_reasons)

    @property
    def drift_reason(self) -> str | None:
        return self.reason_codes[0] if self.reason_codes else None

    def to_dict(self) -> dict[str, object]:
        return {
            "compatible": self.compatible,
            "drift_reasons": [reason.to_dict() for reason in self.drift_reasons],
        }

    def require_compatible(self) -> None:
        if not self.compatible:
            raise RSIFingerprintError("drift", reasons=self.reason_codes)


_COMPARABLE_FIELDS = (
    "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256",
    "solver_id", "solver_settings", "actor_fingerprint", "verifier_fingerprint",
    "curriculum_fingerprint", "target_judge_fingerprint",
)


def compare_fingerprint_contracts(
    expected: RSIFingerprintContract,
    actual: RSIFingerprintContract,
) -> FingerprintComparison:
    """Compare all identities, rejecting invalid inputs before comparing any field."""

    if not isinstance(expected, RSIFingerprintContract):
        raise RSIFingerprintError("expected_invalid")
    if not isinstance(actual, RSIFingerprintContract):
        raise RSIFingerprintError("actual_invalid")
    reasons = tuple(
        FingerprintDriftReason(field, getattr(expected, field), getattr(actual, field))
        for field in _COMPARABLE_FIELDS
        if getattr(expected, field) != getattr(actual, field)
    )
    return FingerprintComparison(not reasons, reasons)


def ensure_fingerprint_compatible(
    expected: RSIFingerprintContract,
    actual: RSIFingerprintContract,
) -> FingerprintComparison:
    """Compare and raise a stable drift error unless every pin matches exactly."""

    comparison = compare_fingerprint_contracts(expected, actual)
    comparison.require_compatible()
    return comparison


# Concise aliases for controller call sites.
compare_fingerprints = compare_fingerprint_contracts
require_compatible = ensure_fingerprint_compatible
def canonical_fingerprint_digest(contract: RSIFingerprintContract | Mapping[str, Any]) -> str:
    """Return the digest for a contract object or its strict dictionary form."""

    if isinstance(contract, RSIFingerprintContract):
        return contract.digest()
    return RSIFingerprintContract.from_dict(contract).digest()

__all__ = [
    "RSI_FINGERPRINT_KIND",
    "RSI_FINGERPRINT_SCHEMA_VERSION",
    "FingerprintComparison",
    "FingerprintContract",
    "FingerprintDriftReason",
    "RSIFingerprintContract",
    "RSIFingerprintError",
    "RunFingerprint",
    "canonical_fingerprint_digest",
    "compare_fingerprint_contracts",
    "compare_fingerprints",
    "ensure_fingerprint_compatible",
    "require_compatible",
]
