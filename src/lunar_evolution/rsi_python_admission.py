"""Detached, evidence-only late Python admission records for the RSI ledger.

These post-execution records do not alter a pre-execution run or grant runtime,
evaluation or publication authority.  All nested proof is reparsed before use.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields, replace
from typing import Any, NoReturn

from .python_producer_admission_anchor import parse_python_producer_admission_attempt_anchor
from .python_producer_admission_handoff import parse_python_producer_admission_handoff_file_pin

RSI_PYTHON_ADMISSION_PROTOCOL = "lunar-rsi-python-admission-v1"
MAX_RSI_PYTHON_ADMISSION_BYTES = 512 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST_FIELDS = (
    "original_run_request_sha256", "original_run_record_sha256", "producer_checkpoint_sha256",
    "episode_request_sha256", "native_claim_sha256", "native_plan_sha256", "prepared_journal_sha256",
)
_FIELDS = frozenset({
    "schema_version", "protocol", "run_id", "episode_id", "journal_id", "attempt_id",
    *_DIGEST_FIELDS, "admission_anchor", "handoff_file_pin", "record_sha256", "production_admission",
})


class RSIPythonAdmissionError(ValueError):
    """Fixed-code refusal without caller-controlled paths or child output."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_python_admission_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise RSIPythonAdmissionError(code)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def validate_rsi_python_admission_shapes(
    value: object, *, dto_types: tuple[type, ...] = (), _depth: int = 0,
) -> None:
    """Reject subclasses/callback collections before invoking any DTO serialization.

    Exact tuples are allowed in the in-memory DTO representation only.  JSON parsing
    subsequently requires the exact wire schema and lists.  A small explicit type
    allowlist prevents arbitrary dataclass methods from entering the boundary.
    """
    if _depth > 48:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind in {str, bool, int}:
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        if any(type(key) is not str for key in value):
            _fail("shape_invalid")
        items = value.values()
    elif kind in {list, tuple}:
        items = value
    elif kind in dto_types:
        items = (getattr(value, field.name) for field in fields(value))
    else:
        _fail("shape_invalid")
    for item in items:
        validate_rsi_python_admission_shapes(item, dto_types=dto_types, _depth=_depth + 1)


def _canonical(value: object) -> bytes:
    validate_rsi_python_admission_shapes(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise RSIPythonAdmissionError("json_invalid") from exc
    if len(raw) > MAX_RSI_PYTHON_ADMISSION_BYTES:
        _fail("record_too_large")
    return raw


def _strict_json(value: bytes | str) -> object:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
        if len(raw) > MAX_RSI_PYTHON_ADMISSION_BYTES:
            _fail("record_too_large")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("duplicate_json_key")
                result[key] = item
            return result

        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _value: _fail("json_invalid"))
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, RSIPythonAdmissionError):
            raise
        raise RSIPythonAdmissionError("json_invalid") from exc


@dataclass(frozen=True, slots=True)
class RSIPythonAdmissionRecord:
    """A separate create-only identity for already-retained local evidence."""

    run_id: str
    episode_id: str
    journal_id: str
    attempt_id: str
    original_run_request_sha256: str
    original_run_record_sha256: str
    producer_checkpoint_sha256: str
    episode_request_sha256: str
    native_claim_sha256: str
    native_plan_sha256: str
    prepared_journal_sha256: str
    admission_anchor: dict[str, Any]
    handoff_file_pin: dict[str, Any]
    record_sha256: str | None = None
    production_admission: bool = False
    schema_version: str = "1"
    protocol: str = RSI_PYTHON_ADMISSION_PROTOCOL

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not str or self.schema_version != "1"
                or type(self.protocol) is not str or self.protocol != RSI_PYTHON_ADMISSION_PROTOCOL):
            _fail("schema_invalid")
        if type(self.production_admission) is not bool or self.production_admission:
            _fail("authority_invalid")
        for key in ("run_id", "episode_id", "journal_id", "attempt_id"):
            if type(getattr(self, key)) is not str or _ID.fullmatch(getattr(self, key)) is None:
                _fail("identity_invalid")
        for key in _DIGEST_FIELDS:
            _sha(getattr(self, key))
        if self.record_sha256 is not None:
            _sha(self.record_sha256)
        if type(self.admission_anchor) is not dict or type(self.handoff_file_pin) is not dict:
            _fail("shape_invalid")
        validate_rsi_python_admission_shapes(self.admission_anchor)
        validate_rsi_python_admission_shapes(self.handoff_file_pin)
        try:
            anchor = parse_python_producer_admission_attempt_anchor(self.admission_anchor)
            pin = parse_python_producer_admission_handoff_file_pin(self.handoff_file_pin)
        except (TypeError, ValueError) as exc:
            raise RSIPythonAdmissionError("evidence_invalid") from exc
        if ((anchor.run_id, anchor.journal_id, anchor.attempt_id)
                != (self.run_id, self.journal_id, self.attempt_id)
                or (pin.run_id, pin.journal_id, pin.handoff_sha256)
                != (self.run_id, self.journal_id, anchor.handoff_sha256)):
            _fail("evidence_identity_mismatch")
        # Canonical equality preserves fractional numeric wire types as well as values.
        if (_canonical(anchor.to_dict()) != _canonical(self.admission_anchor)
                or _canonical(pin.to_dict()) != _canonical(self.handoff_file_pin)):
            _fail("evidence_invalid")

    def _body(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self) if field.name != "record_sha256"}

    def digest(self) -> str:
        self.__post_init__()
        return hashlib.sha256(_canonical(self._body())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        digest = self.digest()
        if self.record_sha256 is not None and self.record_sha256 != digest:
            _fail("digest_mismatch")
        return json.loads(_canonical(self._body() | {"record_sha256": digest}))

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> RSIPythonAdmissionRecord:
        if type(value) is not dict or set(value) != _FIELDS:
            _fail("schema_invalid")
        validate_rsi_python_admission_shapes(value)
        _sha(value["record_sha256"])
        detached = json.loads(_canonical(value))
        result = cls(**detached)
        if result.to_json() != _canonical(value):
            _fail("digest_mismatch")
        return result

    @classmethod
    def from_json(cls, value: bytes | str) -> RSIPythonAdmissionRecord:
        result = cls.from_dict(_strict_json(value))
        raw = value if type(value) is bytes else value.encode("utf-8")
        if result.to_json() != raw:
            _fail("noncanonical_json")
        return result


def build_rsi_python_admission_record(**kwargs: Any) -> RSIPythonAdmissionRecord:
    result = RSIPythonAdmissionRecord(**kwargs)
    return RSIPythonAdmissionRecord.from_dict(replace(result, record_sha256=result.digest()).to_dict())


def parse_rsi_python_admission_record(value: object) -> RSIPythonAdmissionRecord:
    if type(value) is RSIPythonAdmissionRecord:
        if value.record_sha256 is None:
            _fail("digest_invalid")
        return RSIPythonAdmissionRecord.from_dict(value.to_dict())
    if type(value) in {bytes, str}:
        return RSIPythonAdmissionRecord.from_json(value)
    return RSIPythonAdmissionRecord.from_dict(value)


__all__ = [
    "MAX_RSI_PYTHON_ADMISSION_BYTES", "RSI_PYTHON_ADMISSION_PROTOCOL", "RSIPythonAdmissionError",
    "RSIPythonAdmissionRecord", "build_rsi_python_admission_record", "parse_rsi_python_admission_record",
    "validate_rsi_python_admission_shapes",
]
