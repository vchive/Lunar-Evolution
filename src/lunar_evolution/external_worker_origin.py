"""Stateless HMAC origin checks for exact external-worker receipt bytes.

The trusted registry binds a shared secret to a worker and host/boot namespace.
It does not observe an OS boot, consume a challenge, acquire a lease, inspect a
remote process, or grant native result/publication authority. Identical messages
can verify repeatedly until an authoritative assignment ledger consumes them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

MAX_WORKER_ORIGIN_BYTES = 8192
MAX_WORKER_ORIGIN_RECEIPT_BYTES = 1024 * 1024
_MAX_REGISTRY_ENTRIES = 1024
_SCHEMA = "lunar-external-worker-origin-v1"
_ALGORITHM = "hmac-sha256"
_DOMAIN = b"lunar-external-worker-origin-v1\x00"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CONTEXT_FIELDS = (
    "controller_id", "run_id", "task_id", "episode_id", "context_kind",
    "context_sha256", "controller_challenge", "assignment_generation",
)
_IDENTITY_FIELDS = ("worker_id", "host_id", "host_boot_id", "key_id")
_WIRE_FIELDS = frozenset({
    "schema_version", "algorithm", *_IDENTITY_FIELDS, *_CONTEXT_FIELDS,
    "profile_sha256", "receipt_sha256", "mac_sha256",
})


class WorkerOriginError(ValueError):
    """Fixed error codes; no caller bytes or secret values enter error text."""


def _identifier(value: object) -> str:
    if type(value) is not str or not value.strip() or any(c in value for c in "\x00\r\n"):
        raise WorkerOriginError("worker_origin_identity_invalid")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise WorkerOriginError("worker_origin_identity_invalid") from exc
    if size > 256:
        raise WorkerOriginError("worker_origin_identity_invalid")
    return value


def _sha(value: object, *, code: str = "worker_origin_digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise WorkerOriginError(code)
    return value


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _receipt_digest(receipt: object) -> str:
    if (
        type(receipt) is not bytes or not receipt
        or len(receipt) > MAX_WORKER_ORIGIN_RECEIPT_BYTES
    ):
        raise WorkerOriginError("worker_origin_receipt_invalid")
    return hashlib.sha256(receipt).hexdigest()


def new_worker_origin_challenge() -> str:
    """Generate a controller challenge; its later atomic consumption is separate."""
    return secrets.token_hex(32)


@dataclass(frozen=True, slots=True)
class WorkerOriginKey:
    """Trusted per-worker shared secret, never serialized or included in repr."""

    worker_id: str
    host_id: str
    host_boot_id: str
    key_id: str
    secret_key: bytes = field(repr=False, compare=False)
    revoked: bool = False

    def __post_init__(self) -> None:
        for name in _IDENTITY_FIELDS:
            _identifier(getattr(self, name))
        if type(self.secret_key) is not bytes or not 32 <= len(self.secret_key) <= 4096:
            raise WorkerOriginError("worker_origin_secret_invalid")
        if type(self.revoked) is not bool:
            raise WorkerOriginError("worker_origin_revocation_invalid")


class WorkerOriginRegistry:
    """Detached fixed registry, with one independent key per registered worker."""

    __slots__ = ("__keys",)

    def __init__(self, keys: Iterable[WorkerOriginKey]) -> None:
        records: dict[str, WorkerOriginKey] = {}
        key_ids: set[str] = set()
        for key in keys:
            if type(key) is not WorkerOriginKey:
                raise WorkerOriginError("worker_origin_registry_key_invalid")
            # Detach even frozen caller objects before retaining registry authority.
            record = WorkerOriginKey(
                key.worker_id, key.host_id, key.host_boot_id, key.key_id,
                key.secret_key, key.revoked,
            )
            if len(records) >= _MAX_REGISTRY_ENTRIES:
                raise WorkerOriginError("worker_origin_registry_limit")
            if record.worker_id in records or record.key_id in key_ids:
                raise WorkerOriginError("worker_origin_registry_duplicate")
            if any(hmac.compare_digest(record.secret_key, old.secret_key) for old in records.values()):
                raise WorkerOriginError("worker_origin_registry_secret_reused")
            records[record.worker_id] = record
            key_ids.add(record.key_id)
        self.__keys = MappingProxyType(records)

    def __repr__(self) -> str:
        return f"WorkerOriginRegistry(workers={len(self.__keys)}, secrets_redacted=True)"

    def _lookup(self, worker_id: str) -> WorkerOriginKey:
        record = self.__keys.get(worker_id)
        if record is None:
            raise WorkerOriginError("worker_origin_worker_unknown")
        if record.revoked:
            raise WorkerOriginError("worker_origin_worker_revoked")
        return record

    def worker_identity(self, worker_id: str) -> dict[str, str]:
        """Resolve an active registered identity without disclosing its secret."""
        record = self._lookup(_identifier(worker_id))
        return {name: getattr(record, name) for name in _IDENTITY_FIELDS}


@dataclass(frozen=True, slots=True)
class WorkerOriginContext:
    """Independently retained original assignment context, not wire authority."""

    controller_id: str
    run_id: str
    task_id: str
    episode_id: str
    context_kind: str
    context_sha256: str
    controller_challenge: str
    assignment_generation: int

    def __post_init__(self) -> None:
        for name in ("controller_id", "run_id", "task_id", "episode_id"):
            _identifier(getattr(self, name))
        if type(self.context_kind) is not str or self.context_kind not in {
            "native-claim", "launch-context",
        }:
            raise WorkerOriginError("worker_origin_context_kind_invalid")
        _sha(self.context_sha256)
        _sha(self.controller_challenge, code="worker_origin_challenge_invalid")
        if (
            type(self.assignment_generation) is not int
            or not 1 <= self.assignment_generation <= (1 << 63) - 1
        ):
            raise WorkerOriginError("worker_origin_generation_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _CONTEXT_FIELDS}

    @classmethod
    def from_dict(cls, value: object) -> WorkerOriginContext:
        """Parse the exact context shape retained by an authoritative assignment."""
        if type(value) is not dict or set(value) != set(_CONTEXT_FIELDS):
            raise WorkerOriginError("worker_origin_context_fields_invalid")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class VerifiedWorkerOrigin:
    """Authenticated shared-key origin only; no replay or execution authority."""

    worker_id: str
    host_id: str
    host_boot_id: str
    key_id: str
    context: WorkerOriginContext
    profile_sha256: str
    receipt_sha256: str
    wire_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **{name: getattr(self, name) for name in _IDENTITY_FIELDS},
            **self.context.to_dict(),
            "profile_sha256": self.profile_sha256,
            "receipt_sha256": self.receipt_sha256,
            "wire_sha256": self.wire_sha256,
        }


def _context_dict(context: object) -> dict[str, Any]:
    if type(context) is not WorkerOriginContext:
        raise WorkerOriginError("worker_origin_context_invalid")
    context.__post_init__()
    return context.to_dict()


def _mac(key: WorkerOriginKey, unsigned: dict[str, Any]) -> str:
    return hmac.new(key.secret_key, _DOMAIN + _canonical(unsigned), hashlib.sha256).hexdigest()


def sign_worker_origin(
    *, key: WorkerOriginKey, context: WorkerOriginContext, profile_sha256: str,
    receipt: bytes,
) -> bytes:
    """Sign exact receipt bytes in the trusted wrapper, without exporting the secret."""
    if type(key) is not WorkerOriginKey:
        raise WorkerOriginError("worker_origin_key_invalid")
    key.__post_init__()
    if key.revoked:
        raise WorkerOriginError("worker_origin_worker_revoked")
    unsigned = {
        "schema_version": _SCHEMA, "algorithm": _ALGORITHM,
        **{name: getattr(key, name) for name in _IDENTITY_FIELDS},
        **_context_dict(context), "profile_sha256": _sha(profile_sha256),
        "receipt_sha256": _receipt_digest(receipt),
    }
    raw = _canonical({**unsigned, "mac_sha256": _mac(key, unsigned)})
    if len(raw) > MAX_WORKER_ORIGIN_BYTES:
        raise WorkerOriginError("worker_origin_wire_limit")
    return raw


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise WorkerOriginError("worker_origin_wire_duplicate_key")
        result[key] = value
    return result


def _constant(_value: str) -> Any:
    raise WorkerOriginError("worker_origin_wire_invalid")


def _parse(raw: object) -> tuple[dict[str, Any], WorkerOriginContext]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_WORKER_ORIGIN_BYTES:
        raise WorkerOriginError("worker_origin_wire_invalid")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
        )
    except WorkerOriginError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WorkerOriginError("worker_origin_wire_invalid") from exc
    if type(value) is not dict or set(value) != _WIRE_FIELDS:
        raise WorkerOriginError("worker_origin_wire_fields_invalid")
    if value["schema_version"] != _SCHEMA or value["algorithm"] != _ALGORITHM:
        raise WorkerOriginError("worker_origin_wire_version_invalid")
    for name in _IDENTITY_FIELDS:
        _identifier(value[name])
    for name in ("profile_sha256", "receipt_sha256", "mac_sha256"):
        _sha(value[name])
    context = WorkerOriginContext.from_dict({name: value[name] for name in _CONTEXT_FIELDS})
    if _canonical(value) != raw:
        raise WorkerOriginError("worker_origin_wire_noncanonical")
    return value, context


def verify_worker_origin(
    raw: bytes, *, registry: WorkerOriginRegistry,
    expected_context: WorkerOriginContext, expected_profile_sha256: str, receipt: bytes,
) -> VerifiedWorkerOrigin:
    """Verify exact origin/context/receipt binding, without consuming the challenge.

    The expected context must come from the original controller assignment, not
    from the signed wire. Success authenticates a shared-key holder only. A later
    authoritative transaction must enforce replay, claim and generation gates.
    """
    if type(registry) is not WorkerOriginRegistry:
        raise WorkerOriginError("worker_origin_registry_invalid")
    expected = _context_dict(expected_context)
    expected_profile = _sha(expected_profile_sha256)
    receipt_sha = _receipt_digest(receipt)
    value, context = _parse(raw)
    key = registry._lookup(value["worker_id"])
    if value["key_id"] != key.key_id:
        raise WorkerOriginError("worker_origin_key_mismatch")
    if value["host_id"] != key.host_id or value["host_boot_id"] != key.host_boot_id:
        raise WorkerOriginError("worker_origin_host_mismatch")
    if context.to_dict() != expected:
        raise WorkerOriginError("worker_origin_context_mismatch")
    if value["profile_sha256"] != expected_profile:
        raise WorkerOriginError("worker_origin_profile_mismatch")
    if value["receipt_sha256"] != receipt_sha:
        raise WorkerOriginError("worker_origin_receipt_mismatch")
    unsigned = {name: item for name, item in value.items() if name != "mac_sha256"}
    if not hmac.compare_digest(value["mac_sha256"], _mac(key, unsigned)):
        raise WorkerOriginError("worker_origin_mac_invalid")
    return VerifiedWorkerOrigin(
        key.worker_id, key.host_id, key.host_boot_id, key.key_id, context,
        expected_profile, receipt_sha, hashlib.sha256(raw).hexdigest(),
    )
