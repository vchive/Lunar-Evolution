"""Strict, create-only observations for mixed published/rejected producer lineage.

These descriptors do not grant execution or recovery authority. The owner must
compare independently retained original file pins and native evidence separately.
V1 descriptors, wire bytes and snapshot permissions remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from pathlib import Path, PosixPath, WindowsPath
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_evaluation_spec import strict_json
from .producer_bundle_lineage import (
    MAX_LINEAGE_BATCHES,
    MAX_LINEAGE_DESCRIPTOR_BYTES,
    LineageSnapshotPin,
    ProducerBundleLineageError,
    _absolute_path,
    _create_lineage_file,
    _id,
    _int,
    _observe_file,
    _sha,
    lineage_directory,
)

LINEAGE_V2_PROTOCOL = "lunar-producer-bundle-lineage-v2"
LINEAGE_V2_SCHEMA_VERSION = "2"


class ProducerBundleLineageV2Error(ProducerBundleLineageError):
    """A fixed-code refusal at the v2 data/filesystem boundary."""

    def __init__(self, code: str) -> None:
        super().__init__("v2_" + code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundleLineageV2Error(code)


def _plain(value: object, *, depth: int = 0) -> None:
    if depth > 6:
        _fail("descriptor_too_deep")
    if type(value) is dict:
        if len(value) > 32 or any(type(key) is not str for key in value):
            _fail("schema_invalid")
        for item in value.values():
            _plain(item, depth=depth + 1)
    elif type(value) is list:
        if len(value) > 32:
            _fail("schema_invalid")
        for item in value:
            _plain(item, depth=depth + 1)
    elif value is not None and type(value) not in {str, int}:
        _fail("schema_invalid")


def _canonical(value: object) -> bytes:
    _plain(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundleLineageV2Error("canonical_invalid") from exc
    if len(raw) > MAX_LINEAGE_DESCRIPTOR_BYTES:
        _fail("descriptor_too_large")
    return raw


def _normalized_snapshot_pin(pin: object) -> LineageSnapshotPin:
    if type(pin) is not LineageSnapshotPin:
        _fail("snapshot_pin_invalid")
    # Do not invoke a supplied DTO subclass or nested callback during validation.
    raw = {field.name: getattr(pin, field.name) for field in fields(LineageSnapshotPin)}
    _plain(raw)
    return LineageSnapshotPin.from_dict(raw)


def _pin_payload(pin: object, name: str) -> dict[str, object]:
    normalized = _normalized_snapshot_pin(pin)
    if normalized.name != name:
        _fail("snapshot_name_invalid")
    return normalized.to_dict()


def _wire(value: object, cls: type) -> dict[str, object]:
    if type(value) is not dict:
        _fail("schema_invalid")
    _plain(value)
    if set(value) != {field.name for field in fields(cls)}:
        _fail("schema_invalid")
    raw = dict(value)
    given = _sha(raw["descriptor_sha256"], "descriptor_digest_invalid")
    body = dict(raw)
    body.pop("descriptor_sha256")
    if hashlib.sha256(_canonical(body)).hexdigest() != given:
        _fail("descriptor_digest_mismatch")
    return raw


def _association(group: tuple[object, ...], *, previous: bool) -> bool:
    if all(value is None for value in group):
        return False
    if any(value is None for value in group):
        _fail("predecessor_incomplete")
    _id(group[0], "predecessor_journal_invalid")
    if previous:
        if type(group[1]) is not str or group[1] not in {"published", "all_rejected"}:
            _fail("previous_outcome_invalid")
        digests = group[2:]
    else:
        digests = group[1:]
    for digest in digests:
        _sha(digest, "predecessor_digest_invalid")
    return True


def _seal(instance: ProducerLineageBeforeIntentV2 | ProducerLineageRejectedTerminalV2, payload: dict[str, object], *, initialize: bool) -> str:
    expected = hashlib.sha256(_canonical(payload)).hexdigest()
    given = instance.descriptor_sha256
    if initialize and given is None:
        object.__setattr__(instance, "descriptor_sha256", expected)
    elif _sha(given, "descriptor_digest_invalid") != expected:
        _fail("descriptor_digest_mismatch")
    return expected


@dataclass(frozen=True, slots=True)
class ProducerLineageBeforeIntentV2:
    """Separate the previous attempted terminal from the latest published head.

    All-null predecessor groups are explicit; descriptors alone do not establish
    chain ordering or authenticate those predecessor declarations.
    """

    run_id: str
    journal_id: str
    ordinal: int
    previous_attempt_journal_id: str | None
    previous_attempt_outcome: str | None
    previous_attempt_terminal_sha256: str | None
    previous_attempt_lineage_sha256: str | None
    published_predecessor_journal_id: str | None
    published_predecessor_terminal_sha256: str | None
    published_predecessor_lineage_sha256: str | None
    archive: LineageSnapshotPin
    state: LineageSnapshotPin
    descriptor_sha256: str | None = None
    kind: str = "before-v2"
    schema_version: str = LINEAGE_V2_SCHEMA_VERSION
    protocol: str = LINEAGE_V2_PROTOCOL

    def __post_init__(self) -> None:
        _seal(self, self._validated_payload(), initialize=True)

    def _validated_payload(self) -> dict[str, object]:
        if type(self) is not ProducerLineageBeforeIntentV2:
            _fail("descriptor_invalid")
        _id(self.run_id)
        _id(self.journal_id)
        _int(self.ordinal, "ordinal_invalid", maximum=MAX_LINEAGE_BATCHES - 1)
        if (type(self.kind) is not str or self.kind != "before-v2"
                or type(self.schema_version) is not str or self.schema_version != LINEAGE_V2_SCHEMA_VERSION
                or type(self.protocol) is not str or self.protocol != LINEAGE_V2_PROTOCOL):
            _fail("schema_invalid")
        previous = (self.previous_attempt_journal_id, self.previous_attempt_outcome,
                    self.previous_attempt_terminal_sha256, self.previous_attempt_lineage_sha256)
        published = (self.published_predecessor_journal_id, self.published_predecessor_terminal_sha256,
                     self.published_predecessor_lineage_sha256)
        has_previous = _association(previous, previous=True)
        has_published = _association(published, previous=False)
        if self.ordinal == 0 and (has_previous or has_published):
            _fail("genesis_predecessor_invalid")
        if self.ordinal > 0 and not has_previous:
            _fail("predecessor_missing")
        if self.journal_id in {self.previous_attempt_journal_id, self.published_predecessor_journal_id}:
            _fail("predecessor_self_reference")
        if self.previous_attempt_outcome == "published" and published != (previous[0], previous[2], previous[3]):
            _fail("published_predecessor_mismatch")
        if (self.previous_attempt_outcome == "all_rejected" and has_published
                and self.previous_attempt_journal_id == self.published_predecessor_journal_id):
            _fail("rejected_published_predecessor_invalid")
        payload = {field.name: getattr(self, field.name) for field in fields(type(self))
                   if field.name not in {"descriptor_sha256", "archive", "state"}}
        payload["archive"] = _pin_payload(self.archive, "archive-before.snapshot")
        payload["state"] = _pin_payload(self.state, "state-before.snapshot")
        return payload

    def to_dict(self) -> dict[str, object]:
        payload = self._validated_payload()
        payload["descriptor_sha256"] = _seal(self, payload, initialize=False)
        return payload

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return _seal(self, self._validated_payload(), initialize=False)

    @classmethod
    def from_dict(cls, value: object) -> ProducerLineageBeforeIntentV2:
        raw = _wire(value, cls)
        raw["archive"] = LineageSnapshotPin.from_dict(raw["archive"])
        raw["state"] = LineageSnapshotPin.from_dict(raw["state"])
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProducerLineageRejectedTerminalV2:
    """Unchanged population plus the complete ordered native rejection outcome.

    ``rejection_manifest_sha256`` hashes the entire original pretty file bytes.
    ``terminal_marker_sha256`` hashes the canonical manifest body without its
    marker field. These distinct hashes must never be substituted for each other.
    """

    run_id: str
    journal_id: str
    episode_id: str
    ordinal: int
    before_sha256: str
    prepared_journal_sha256: str
    terminal_journal_sha256: str
    rejection_manifest_sha256: str
    terminal_marker_sha256: str
    candidate_ids: tuple[str, ...]
    archive_sha256: str
    state_sha256: str
    descriptor_sha256: str | None = None
    kind: str = "rejected"
    schema_version: str = LINEAGE_V2_SCHEMA_VERSION
    protocol: str = LINEAGE_V2_PROTOCOL

    def __post_init__(self) -> None:
        _seal(self, self._validated_payload(), initialize=True)

    def _validated_payload(self) -> dict[str, object]:
        if type(self) is not ProducerLineageRejectedTerminalV2:
            _fail("descriptor_invalid")
        for value in (self.run_id, self.journal_id, self.episode_id):
            _id(value)
        _int(self.ordinal, "ordinal_invalid", maximum=MAX_LINEAGE_BATCHES - 1)
        if (type(self.kind) is not str or self.kind != "rejected"
                or type(self.schema_version) is not str or self.schema_version != LINEAGE_V2_SCHEMA_VERSION
                or type(self.protocol) is not str or self.protocol != LINEAGE_V2_PROTOCOL):
            _fail("schema_invalid")
        for value in (self.before_sha256, self.prepared_journal_sha256, self.terminal_journal_sha256,
                      self.rejection_manifest_sha256, self.terminal_marker_sha256,
                      self.archive_sha256, self.state_sha256):
            _sha(value)
        if type(self.candidate_ids) is not tuple or not 1 <= len(self.candidate_ids) <= 32:
            _fail("candidates_invalid")
        for candidate in self.candidate_ids:
            _id(candidate, "candidate_invalid")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            _fail("candidates_invalid")
        payload = {field.name: getattr(self, field.name) for field in fields(type(self))
                   if field.name not in {"descriptor_sha256", "candidate_ids"}}
        payload["candidate_ids"] = list(self.candidate_ids)
        return payload

    def to_dict(self) -> dict[str, object]:
        payload = self._validated_payload()
        payload["descriptor_sha256"] = _seal(self, payload, initialize=False)
        return payload

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return _seal(self, self._validated_payload(), initialize=False)

    @classmethod
    def from_dict(cls, value: object) -> ProducerLineageRejectedTerminalV2:
        raw = _wire(value, cls)
        if type(raw["candidate_ids"]) is not list:
            _fail("candidates_invalid")
        raw["candidate_ids"] = tuple(raw["candidate_ids"])
        return cls(**raw)  # type: ignore[arg-type]


def parse_lineage_v2_descriptor(value: object) -> ProducerLineageBeforeIntentV2 | ProducerLineageRejectedTerminalV2:
    """Parse observations only; encoded input must contain exact canonical bytes."""
    encoded = None
    if type(value) is dict:
        _plain(value)
        raw = value
    elif type(value) in {bytes, str}:
        try:
            encoded = value if type(value) is bytes else value.encode("utf-8")
            raw = strict_json(encoded, MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc:
            raise ProducerBundleLineageV2Error("json_invalid") from exc
    elif type(value) in {Path, PosixPath, WindowsPath}:
        try:
            encoded = _files.read_regular_file(_absolute_path(value), MAX_LINEAGE_DESCRIPTOR_BYTES)
            raw = strict_json(encoded, MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc:
            raise ProducerBundleLineageV2Error("read_invalid") from exc
    else:
        _fail("schema_invalid")
    _plain(raw)
    if type(raw) is not dict:
        _fail("schema_invalid")
    if encoded is not None and encoded != _canonical(raw):
        _fail("descriptor_noncanonical")
    if raw.get("kind") == "before-v2":
        return ProducerLineageBeforeIntentV2.from_dict(raw)
    if raw.get("kind") == "rejected":
        return ProducerLineageRejectedTerminalV2.from_dict(raw)
    _fail("kind_invalid")


def persist_lineage_v2_descriptor(
    workspace: str | Path, descriptor: object, *, expected_file_pin: LineageSnapshotPin | None = None,
) -> tuple[Path, LineageSnapshotPin]:
    """Create a descriptor; an existing file requires its original independent pin."""
    if type(descriptor) not in {ProducerLineageBeforeIntentV2, ProducerLineageRejectedTerminalV2}:
        _fail("descriptor_invalid")
    raw = descriptor.to_json()
    normalized = parse_lineage_v2_descriptor(raw)
    if normalized != descriptor:
        _fail("descriptor_invalid")
    if expected_file_pin is not None:
        expected_file_pin = _normalized_snapshot_pin(expected_file_pin)
    return _create_lineage_file(workspace, descriptor.journal_id, filename=f"{descriptor.kind}.json",
                                raw=raw, expected_file_pin=expected_file_pin)


def read_lineage_v2_descriptor_pinned(
    workspace: str | Path, journal_id: str, *, kind: str, expected_file_pin: LineageSnapshotPin,
) -> ProducerLineageBeforeIntentV2 | ProducerLineageRejectedTerminalV2:
    """Read a fixed derived path using the independently held original stat/bytes."""
    if type(kind) is not str or kind not in {"before-v2", "rejected"}:
        _fail("kind_invalid")
    pin = _normalized_snapshot_pin(expected_file_pin)
    if pin.name != f"{kind}.json":
        _fail("snapshot_name_invalid")
    path = lineage_directory(workspace, journal_id) / f"{kind}.json"
    raw, _ = _observe_file(path, name=path.name, maximum=MAX_LINEAGE_DESCRIPTOR_BYTES, expected_pin=pin)
    descriptor = parse_lineage_v2_descriptor(raw)
    if descriptor.journal_id != journal_id or descriptor.kind != kind:
        _fail("association_invalid")
    return descriptor
