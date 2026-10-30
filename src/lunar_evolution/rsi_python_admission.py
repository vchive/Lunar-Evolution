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
from typing import TYPE_CHECKING, Any, NoReturn

from .python_producer_admission_anchor import parse_python_producer_admission_attempt_anchor
from .python_producer_admission_handoff import parse_python_producer_admission_handoff_file_pin

if TYPE_CHECKING:
    from .producer_bundle_publication import ProducerBundlePublicationJournal
    from .rsi_native_plan import NativeRSIExecutionPlan

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


@dataclass(frozen=True, slots=True)
class _ParsedRSIPythonAdmissionReference:
    """One freshly validated checkpoint reference and its parsed evidence DTOs.

    This context is private to one SQLite history walk. Identical canonical
    bytes may reuse it within that call; it is never persisted, shared between
    calls, or returned from public parser APIs or checkpoint payloads.
    """

    reference: dict[str, Any]
    plan: NativeRSIExecutionPlan
    journal: ProducerBundlePublicationJournal
    canonical_bytes: bytes


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
    if value is None or kind is str or kind is bool or kind is int:
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        for key in value:
            if type(key) is not str:
                _fail("shape_invalid")
        items = value.values()
    elif kind is list or kind is tuple:
        items = value
    else:
        for dto_type in dto_types:
            if kind is dto_type:
                items = (getattr(value, field.name) for field in fields(value))
                break
        else:
            _fail("shape_invalid")
    for item in items:
        # Keep the child depth/type/finiteness gate fresh without a recursive
        # Python call for scalar leaves. DTO fields must remain lazy above.
        child_depth = _depth + 1
        if child_depth > 48:
            _fail("shape_invalid")
        child_kind = type(item)
        if item is None or child_kind is str or child_kind is bool or child_kind is int:
            continue
        if child_kind is float:
            if not math.isfinite(item):
                _fail("shape_invalid")
            continue
        validate_rsi_python_admission_shapes(item, dto_types=dto_types, _depth=child_depth)


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
    if type(value) is not bytes and type(value) is not str:
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
    def _from_dict_and_json(cls, value: object) -> tuple[RSIPythonAdmissionRecord, bytes]:
        """Return fresh detached evidence and the canonical bytes checked here.

        The bytes live only in this parser invocation. They are not retained on
        the record or reused by subsequent validation/serialization calls.
        """
        if type(value) is not dict:
            _fail("schema_invalid")
        if any(type(key) is not str for key in value):
            _fail("shape_invalid")
        if set(value) != _FIELDS:
            _fail("schema_invalid")
        validate_rsi_python_admission_shapes(value)
        _sha(value["record_sha256"])
        canonical = _canonical(value)
        detached = json.loads(canonical)
        result = cls(**detached)
        if result.to_json() != canonical:
            _fail("digest_mismatch")
        return result, canonical

    @classmethod
    def from_dict(cls, value: object) -> RSIPythonAdmissionRecord:
        result, _canonical_raw = cls._from_dict_and_json(value)
        return result

    @classmethod
    def from_json(cls, value: bytes | str) -> RSIPythonAdmissionRecord:
        result, canonical = cls._from_dict_and_json(_strict_json(value))
        raw = value if type(value) is bytes else value.encode("utf-8")
        if canonical != raw:
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
    if type(value) is bytes or type(value) is str:
        return RSIPythonAdmissionRecord.from_json(value)
    return RSIPythonAdmissionRecord.from_dict(value)


_REFERENCE_FIELDS = frozenset({
    "journal_id", "attempt_id", "record_sha256", "native_plan", "prepared_journal",
})


def _parse_rsi_python_admission_reference_context(
    value: object,
    *,
    previous_context: _ParsedRSIPythonAdmissionReference | None = None,
) -> _ParsedRSIPythonAdmissionReference:
    """Parse one bounded complete recovery context and retain its DTOs privately."""
    from .producer_bundle_publication import parse_producer_bundle_publication_journal
    from .rsi_native_plan import NativeRSIExecutionPlan

    if type(value) is not dict:
        _fail("reference_invalid")
    if any(type(key) is not str for key in value):
        _fail("shape_invalid")
    if set(value) != _REFERENCE_FIELDS:
        _fail("reference_invalid")
    validate_rsi_python_admission_shapes(value)
    for name in ("journal_id", "attempt_id"):
        if type(value[name]) is not str or _ID.fullmatch(value[name]) is None:
            _fail("reference_invalid")
    _sha(value["record_sha256"])
    try:
        canonical = _canonical(value)
        if previous_context is not None:
            if (type(previous_context) is not _ParsedRSIPythonAdmissionReference
                    or type(previous_context.canonical_bytes) is not bytes):
                _fail("reference_invalid")
            # Only the preceding validated row of this history walk supplies
            # this private context. Fresh shape/depth/finite/size checks above
            # remain necessary even when its complete canonical bytes match.
            if canonical == previous_context.canonical_bytes:
                return previous_context
        detached = json.loads(canonical)
        plan = NativeRSIExecutionPlan.from_dict(detached["native_plan"])
        journal = parse_producer_bundle_publication_journal(detached["prepared_journal"])
        if (journal.state != "prepared" or journal.publication_phase != "preflight"
                or journal.python_handoff_file_pin is None or journal.python_handoff_sha256 is None
                or journal.native_execution_receipt_sha256 is None
                or (plan.run_id, plan.journal_id, plan.parent_task_id, plan.task_id)
                != (journal.run_id, journal.journal_id, journal.parent_task_id, journal.task_id)
                or plan.journal_id != detached["journal_id"]
                or _canonical(plan.to_dict()) != _canonical(detached["native_plan"])
                or _canonical(journal.to_dict()) != _canonical(detached["prepared_journal"])):
            _fail("reference_invalid")
        # Older DTO parsers accept zero digests; this later trust boundary does not.
        for field, item in detached["native_plan"].items():
            if field.endswith("sha256"):
                _sha(item)
        return _ParsedRSIPythonAdmissionReference(detached, plan, journal, canonical)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RSIPythonAdmissionError("reference_invalid") from exc


def parse_rsi_python_admission_reference(value: object) -> dict[str, Any]:
    """Reparse a bounded complete recovery context without invoking caller methods."""
    return _parse_rsi_python_admission_reference_context(value).reference


def validate_rsi_python_admission_reference_record(
    reference: object, record: object, *, run_id: str, episode_id: str,
) -> dict[str, Any]:
    """Bind the full original wires to the separately retained evidence identity."""
    from .producer_bundle_publication import parse_producer_bundle_publication_journal
    from .rsi_native_plan import NativeRSIExecutionPlan

    ref = parse_rsi_python_admission_reference(reference)
    retained = parse_rsi_python_admission_record(record)
    plan = NativeRSIExecutionPlan.from_dict(ref["native_plan"])
    journal = parse_producer_bundle_publication_journal(ref["prepared_journal"])
    if ((retained.run_id, retained.episode_id) != (run_id, episode_id)
            or (ref["journal_id"], ref["attempt_id"], ref["record_sha256"])
            != (retained.journal_id, retained.attempt_id, retained.record_sha256)
            or (plan.run_id, plan.request.episode_id) != (run_id, episode_id)
            or plan.plan_sha256 != retained.native_plan_sha256
            or plan.request_sha256 != retained.episode_request_sha256
            or journal.digest() != retained.prepared_journal_sha256
            or journal.python_handoff_file_pin is None
            or _canonical(journal.python_handoff_file_pin.to_dict()) != _canonical(retained.handoff_file_pin)):
        _fail("reference_record_mismatch")
    return ref


def build_rsi_python_admission_reference(
    record: object, *, native_plan: object, prepared_journal: object,
) -> dict[str, Any]:
    """Build a detached reference from exact already-reparsed canonical wire dictionaries."""
    retained = parse_rsi_python_admission_record(record)
    return validate_rsi_python_admission_reference_record({
        "journal_id": retained.journal_id, "attempt_id": retained.attempt_id,
        "record_sha256": retained.record_sha256, "native_plan": native_plan,
        "prepared_journal": prepared_journal,
    }, retained, run_id=retained.run_id, episode_id=retained.episode_id)


def parse_rsi_python_admission_references(value: object) -> dict[str, dict[str, Any]]:
    """Validate the optional episode map before serialization or any evidence I/O."""
    return _parse_rsi_python_admission_references_with_context(value)[0]


def _parse_rsi_python_admission_references_with_context(
    value: object,
    *,
    retain_context: bool = False,
    reuse_contexts: dict[str, _ParsedRSIPythonAdmissionReference] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, _ParsedRSIPythonAdmissionReference]]:
    """Parse references, optionally reusing the preceding row's call-local DTOs.

    The history walker alone supplies ``reuse_contexts``. Public parser calls
    use the default and always reparse. Reuse does not preserve repeated
    observations of arbitrary parser/backend rebinding within the same walk.
    """
    if type(value) is not dict:
        _fail("reference_invalid")
    if reuse_contexts is not None and type(reuse_contexts) is not dict:
        _fail("reference_invalid")
    validate_rsi_python_admission_shapes(value)
    result: dict[str, dict[str, Any]] = {}
    contexts: dict[str, _ParsedRSIPythonAdmissionReference] = {}
    canonical_size = 2  # The enclosing map's braces, including an empty map.
    for episode_id, reference in value.items():
        if _ID.fullmatch(episode_id) is None:
            _fail("reference_invalid")
        previous_context = reuse_contexts.get(episode_id) if reuse_contexts is not None else None
        context = _parse_rsi_python_admission_reference_context(
            reference, previous_context=previous_context,
        )
        result[episode_id] = context.reference
        # The exact-string ID gate permits only unescaped ASCII. Each fresh
        # reference already has its complete bounded canonical UTF-8 bytes.
        canonical_size += len(episode_id) + 3 + len(context.canonical_bytes)
        if retain_context:
            contexts[episode_id] = context
        else:
            del context
    # Sorted key order does not change encoded length. Keep this check after
    # the full traversal so later invalid references still refuse first.
    if result:
        canonical_size += len(result) - 1  # Commas between complete entries.
    if canonical_size > 8 * 1024 * 1024:
        _fail("reference_too_large")
    return result, contexts


__all__ = [
    "MAX_RSI_PYTHON_ADMISSION_BYTES",
    "RSI_PYTHON_ADMISSION_PROTOCOL",
    "RSIPythonAdmissionError",
    "RSIPythonAdmissionRecord",
    "build_rsi_python_admission_record",
    "build_rsi_python_admission_reference",
    "parse_rsi_python_admission_record",
    "parse_rsi_python_admission_reference",
    "parse_rsi_python_admission_references",
    "validate_rsi_python_admission_reference_record",
    "validate_rsi_python_admission_shapes",
]
