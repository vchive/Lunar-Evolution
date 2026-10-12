"""Transport-free, bounded material envelopes for external evolution producers.

The envelope is intentionally smaller than any one producer's native result model.  A producer
such as ShinkaEvolve may write this document and the referenced candidate files into a run-local
directory, but Lunar Evolution never executes the producer or trusts its score.  The adapter verifies the
declared material bytes, converts each candidate source to the existing :class:`SeedManifest`, and
lets the injected local exact harness create the authoritative receipt.

This module does not implement a network client, subprocess launcher, scheduler, or multi-file
candidate importer.  ``candidate_source`` materials are single regular UTF-8 files; auxiliary
producer artifacts must remain outside this envelope until a separate contract defines them.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .algorithm import AlgorithmProblemContract, EvaluationReport
from .evolution import MAX_SOURCE_BYTES
from .seed_handoff import (
    MAX_MATERIAL_REFS,
    MAX_REFERENCE_BYTES,
    SeedAdmissionResult,
    SeedManifest,
    admit_seed_manifest,
)

PRODUCER_RESULT_SCHEMA_VERSION = "1"
PRODUCER_RESULT_PROTOCOL = "lunar-producer-result-v1"
PRODUCER_COMPLETED_STATUS = "completed"
PRODUCER_MATERIAL_KIND = "candidate_source"

MAX_PRODUCER_ENVELOPE_BYTES = 128 * 1024
MAX_PRODUCER_MATERIALS = 32
MAX_PRODUCER_TOTAL_MATERIAL_BYTES = MAX_PRODUCER_MATERIALS * MAX_SOURCE_BYTES
MAX_PRODUCER_PATH_BYTES = 1_024
MAX_PRODUCER_LINEAGE_ITEMS = 64
MAX_PRODUCER_BUDGET_FIELDS = 16
MAX_PRODUCER_BUDGET_VALUE = 10_000_000_000
MAX_PRODUCER_EVIDENCE_NODES = 512
MAX_PRODUCER_EVIDENCE_DEPTH = 8
MAX_PRODUCER_EVIDENCE_BYTES = 64 * 1024

PRODUCER_ROOT_UNSAFE = "producer_root_unsafe"
PRODUCER_ENVELOPE_MISSING = "producer_envelope_missing"
PRODUCER_ENVELOPE_NOT_REGULAR = "producer_envelope_not_regular"
PRODUCER_ENVELOPE_TOO_LARGE = "producer_envelope_too_large"
PRODUCER_ENVELOPE_ENCODING_INVALID = "producer_envelope_encoding_invalid"
PRODUCER_ENVELOPE_JSON_INVALID = "producer_envelope_json_invalid"
PRODUCER_ENVELOPE_SCHEMA_INVALID = "producer_envelope_schema_invalid"
PRODUCER_ENVELOPE_PATH_UNSAFE = "producer_envelope_path_unsafe"
PRODUCER_ENVELOPE_STATUS_INVALID = "producer_envelope_status_invalid"
PRODUCER_CONTRACT_MISMATCH = "producer_contract_mismatch"
PRODUCER_IDENTITY_MISMATCH = "producer_identity_mismatch"
PRODUCER_MATERIALS_EMPTY = "producer_materials_empty"
PRODUCER_MATERIALS_TOO_MANY = "producer_materials_too_many"
PRODUCER_MATERIAL_KIND_UNSUPPORTED = "producer_material_kind_unsupported"
PRODUCER_MATERIAL_PATH_UNSAFE = "producer_material_path_unsafe"
PRODUCER_MATERIAL_MISSING = "producer_material_missing"
PRODUCER_MATERIAL_NOT_REGULAR = "producer_material_not_regular"
PRODUCER_MATERIAL_TOO_LARGE = "producer_material_too_large"
PRODUCER_MATERIAL_SIZE_MISMATCH = "producer_material_size_mismatch"
PRODUCER_MATERIAL_DIGEST_MISMATCH = "producer_material_digest_mismatch"
PRODUCER_MATERIAL_CHANGED = "producer_material_changed"
PRODUCER_EVALUATOR_FINGERPRINT_REQUIRED = "producer_evaluator_fingerprint_required"
PRODUCER_FINGERPRINT_REQUIRED = "producer_fingerprint_required"
PRODUCER_BUDGET_INVALID = "producer_budget_invalid"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_BUDGET_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token)\s*[:=]\s*\S+)"
)
_SCORE_KEYS = frozenset({"fitness", "quality", "reward"})
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "system_prompt",
        "traceback",
    }
)


class ProducerHandoffError(RuntimeError):
    """A fixed-code producer-envelope failure with no path or producer prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CandidateEvaluator(Protocol):
    def __call__(
        self,
        candidate_path: Path,
        contract: AlgorithmProblemContract,
    ) -> EvaluationReport | dict[str, Any]:
        ...


class _DuplicateJsonKey(ValueError):
    pass


def _raise(code: str) -> None:
    raise ProducerHandoffError(code)


def _utf8(value: str, code: str) -> bytes:
    if not isinstance(value, str):
        _raise(code)
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        _raise(code)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _evidence_text(value: str) -> bytes:
    """Allow ordinary JSON prose whitespace while rejecting NULs and lone surrogates."""

    if any(
        unicodedata.category(character) == "Cs"
        or (unicodedata.category(character) == "Cc" and character not in {"\n", "\r", "\t"})
        for character in value
    ):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)


def _canonical_bytes(value: object, code: str = PRODUCER_ENVELOPE_SCHEMA_INVALID) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        _raise(code)
    try:
        return encoded.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise(code)
    return value


def _identifier(value: object, label: str, *, kind: bool = False) -> str:
    pattern = _KIND_RE if kind else _ID_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if _CREDENTIAL_RE.search(value):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return value


def _optional_identifier(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, label)


def _relative_path(value: object, code: str = PRODUCER_MATERIAL_PATH_UNSAFE) -> str:
    try:
        raw = os.fspath(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, RuntimeError):
        _raise(code)
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or "\x00" in raw
        or _CREDENTIAL_RE.search(raw)
    ):
        _raise(code)
    if len(_utf8(raw, code)) > MAX_PRODUCER_PATH_BYTES:
        _raise(code)
    path = Path(raw)
    if path.is_absolute() or raw != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        _raise(code)
    return path.as_posix()


def _strict_object(value: object, allowed: frozenset[str], required: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if set(value) - allowed:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if required - set(value):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return value


def _validate_evidence_tree(value: object, *, depth: int = 0, counter: list[int] | None = None) -> bool:
    """Validate bounded untrusted evidence and report whether a score-like field is present."""

    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_PRODUCER_EVIDENCE_NODES or depth > MAX_PRODUCER_EVIDENCE_DEPTH:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        if len(_evidence_text(value)) > MAX_PRODUCER_EVIDENCE_BYTES:
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if _CREDENTIAL_RE.search(value):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return False
    if isinstance(value, int):
        return False
    if isinstance(value, float):
        if not math.isfinite(value):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return False
    if isinstance(value, list):
        if len(value) > 128:
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return any(
            _validate_evidence_tree(item, depth=depth + 1, counter=counter) for item in value
        )
    if isinstance(value, dict):
        if len(value) > 128:
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        score_present = False
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(_utf8(key, PRODUCER_ENVELOPE_SCHEMA_INVALID)) > 256:
                _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
            if key.casefold() in _FORBIDDEN_EVIDENCE_KEYS or _CREDENTIAL_RE.search(key):
                _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
            normalized = key.casefold()
            score_present = score_present or "score" in normalized or normalized in _SCORE_KEYS
            score_present = (
                _validate_evidence_tree(child, depth=depth + 1, counter=counter) or score_present
            )
        return score_present
    _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)


def _evidence_summary(value: object) -> dict[str, Any]:
    if value == {}:
        return {"present": False, "score_present": False, "payload_sha256": None}
    score_present = _validate_evidence_tree(value)
    encoded = _canonical_bytes(value)
    if len(encoded) > MAX_PRODUCER_EVIDENCE_BYTES:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    payload_sha256 = hashlib.sha256(encoded).hexdigest()
    return {
        "present": True,
        "score_present": score_present,
        "payload_sha256": payload_sha256,
    }


def _summary_from_dict(value: object) -> dict[str, Any]:
    raw = _strict_object(
        value,
        frozenset({"present", "score_present", "payload_sha256"}),
        frozenset({"present", "score_present", "payload_sha256"}),
    )
    present = raw["present"]
    score_present = raw["score_present"]
    payload_sha256 = raw["payload_sha256"]
    if not isinstance(present, bool) or not isinstance(score_present, bool):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if present:
        _digest(payload_sha256, PRODUCER_ENVELOPE_SCHEMA_INVALID)
    elif score_present or payload_sha256 is not None:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return {
        "present": present,
        "score_present": score_present,
        "payload_sha256": payload_sha256,
    }


def _merge_summaries(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    present = bool(first["present"] or second["present"])
    score_present = bool(first["score_present"] or second["score_present"])
    if not present:
        return {"present": False, "score_present": False, "payload_sha256": None}
    return {
        "present": True,
        "score_present": score_present,
        "payload_sha256": _sha256(
            {
                "envelope": dict(first),
                "material": dict(second),
            }
        ),
    }


def _material_refs(value: object) -> list[str]:
    """Detach and bound adapter-supplied provenance references."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    result: list[str] = []
    try:
        iterator = iter(value)
        for _ in range(MAX_MATERIAL_REFS + 1):
            try:
                item = next(iterator)
            except StopIteration:
                break
            encoded = (
                _utf8(item, PRODUCER_ENVELOPE_SCHEMA_INVALID)
                if isinstance(item, str)
                else b""
            )
            if (
                not isinstance(item, str)
                or not item
                or len(encoded) > MAX_REFERENCE_BYTES
                or _CREDENTIAL_RE.search(item)
            ):
                _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
            result.append(encoded.decode("utf-8"))
        else:
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if len(result) != len(set(result)):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    except ProducerHandoffError:
        raise
    except Exception:  # noqa: BLE001 - custom Sequence implementations are untrusted
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return result


def _budget(value: object) -> dict[str, int | float]:
    if not isinstance(value, dict) or not value or len(value) > MAX_PRODUCER_BUDGET_FIELDS:
        _raise(PRODUCER_BUDGET_INVALID)
    result: dict[str, int | float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or _BUDGET_KEY_RE.fullmatch(key) is None:
            _raise(PRODUCER_BUDGET_INVALID)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _raise(PRODUCER_BUDGET_INVALID)
        try:
            finite = math.isfinite(float(item))
        except (OverflowError, ValueError):
            _raise(PRODUCER_BUDGET_INVALID)
        if not finite or item < 0 or item > MAX_PRODUCER_BUDGET_VALUE:
            _raise(PRODUCER_BUDGET_INVALID)
        result[key] = item
    _canonical_bytes(result, PRODUCER_BUDGET_INVALID)
    return result


@dataclass(frozen=True, slots=True)
class ProducerMaterial:
    """One digest-bound material file emitted by a producer."""

    kind: str
    path: str
    size: int
    sha256: str
    lineage: tuple[str, ...] = ()
    external_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identifier(self.kind, "material kind", kind=True))
        object.__setattr__(self, "path", _relative_path(self.path))
        if type(self.size) is not int or not 1 <= self.size <= MAX_SOURCE_BYTES:
            _raise(PRODUCER_MATERIAL_TOO_LARGE)
        object.__setattr__(self, "sha256", _digest(self.sha256, PRODUCER_ENVELOPE_SCHEMA_INVALID))
        if not isinstance(self.lineage, (tuple, list)):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        try:
            lineage = tuple(self.lineage)
        except (TypeError, RecursionError):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if (
            len(lineage) > MAX_PRODUCER_LINEAGE_ITEMS
            or any(not isinstance(item, str) for item in lineage)
            or len(set(lineage)) != len(lineage)
        ):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        object.__setattr__(self, "lineage", tuple(_identifier(item, "lineage") for item in lineage))
        if not isinstance(self.external_evidence, dict):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        # Normalize untrusted producer evidence before it can enter SeedManifest.
        if set(self.external_evidence) == {"present", "score_present", "payload_sha256"}:
            summary = _summary_from_dict(self.external_evidence)
        else:
            summary = _evidence_summary(self.external_evidence)
        object.__setattr__(self, "external_evidence", summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "lineage": list(self.lineage),
            "external_evidence": dict(self.external_evidence),
        }

    @classmethod
    def from_dict(cls, value: object) -> ProducerMaterial:
        raw = _strict_object(
            value,
            frozenset({"kind", "path", "size", "sha256", "lineage", "external_evidence"}),
            frozenset({"kind", "path", "size", "sha256"}),
        )
        lineage = raw.get("lineage", [])
        if not isinstance(lineage, list) or any(not isinstance(item, str) for item in lineage):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        evidence = raw.get("external_evidence", {})
        if not isinstance(evidence, dict):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return cls(
            kind=raw["kind"],  # type: ignore[arg-type]
            path=raw["path"],  # type: ignore[arg-type]
            size=raw["size"],  # type: ignore[arg-type]
            sha256=raw["sha256"],  # type: ignore[arg-type]
            lineage=tuple(lineage),
            external_evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class ProducerResultEnvelope:
    """A strict, transport-neutral producer result containing material references only."""

    schema_version: str
    producer_id: str
    producer_fingerprint: str
    status: Literal["completed", "failed", "cancelled", "unknown"]
    contract_sha256: str
    budget: dict[str, int | float]
    materials: tuple[ProducerMaterial, ...]
    producer_run_id: str | None = None
    external_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCER_RESULT_SCHEMA_VERSION:
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        object.__setattr__(self, "producer_id", _identifier(self.producer_id, "producer_id"))
        object.__setattr__(
            self,
            "producer_fingerprint",
            _digest(self.producer_fingerprint, PRODUCER_FINGERPRINT_REQUIRED),
        )
        if not isinstance(self.status, str) or self.status not in {
            "completed",
            "failed",
            "cancelled",
            "unknown",
        }:
            _raise(PRODUCER_ENVELOPE_STATUS_INVALID)
        object.__setattr__(self, "contract_sha256", _digest(self.contract_sha256, PRODUCER_CONTRACT_MISMATCH))
        object.__setattr__(self, "budget", _budget(self.budget))
        try:
            materials = tuple(self.materials)
        except (TypeError, RecursionError):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if len(materials) > MAX_PRODUCER_MATERIALS:
            _raise(PRODUCER_MATERIALS_TOO_MANY)
        if any(not isinstance(item, ProducerMaterial) for item in materials):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        paths = [item.path for item in materials]
        if len(paths) != len(set(paths)):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if sum(item.size for item in materials) > MAX_PRODUCER_TOTAL_MATERIAL_BYTES:
            _raise(PRODUCER_MATERIAL_TOO_LARGE)
        object.__setattr__(self, "materials", materials)
        object.__setattr__(self, "producer_run_id", _optional_identifier(self.producer_run_id, "producer_run_id"))
        if not isinstance(self.external_evidence, dict):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        if set(self.external_evidence) == {"present", "score_present", "payload_sha256"}:
            summary = _summary_from_dict(self.external_evidence)
        else:
            summary = _evidence_summary(self.external_evidence)
        object.__setattr__(self, "external_evidence", summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "producer_run_id": self.producer_run_id,
            "status": self.status,
            "contract_sha256": self.contract_sha256,
            "budget": dict(self.budget),
            "materials": [item.to_dict() for item in self.materials],
            "external_evidence": dict(self.external_evidence),
        }

    @property
    def envelope_sha256(self) -> str:
        return _sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> ProducerResultEnvelope:
        raw = _strict_object(
            value,
            frozenset(
                {
                    "schema_version",
                    "producer_id",
                    "producer_fingerprint",
                    "producer_run_id",
                    "status",
                    "contract_sha256",
                    "budget",
                    "materials",
                    "external_evidence",
                }
            ),
            frozenset(
                {
                    "schema_version",
                    "producer_id",
                    "producer_fingerprint",
                    "status",
                    "contract_sha256",
                    "budget",
                    "materials",
                }
            ),
        )
        materials = raw["materials"]
        if not isinstance(materials, list):
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return cls(
            schema_version=raw["schema_version"],  # type: ignore[arg-type]
            producer_id=raw["producer_id"],  # type: ignore[arg-type]
            producer_fingerprint=raw["producer_fingerprint"],  # type: ignore[arg-type]
            producer_run_id=raw.get("producer_run_id"),  # type: ignore[arg-type]
            status=raw["status"],  # type: ignore[arg-type]
            contract_sha256=raw["contract_sha256"],  # type: ignore[arg-type]
            budget=raw["budget"],  # type: ignore[arg-type]
            materials=tuple(ProducerMaterial.from_dict(item) for item in materials),
            external_evidence=raw.get("external_evidence", {}),
        )


def _open_flags(*, directory: bool = False) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return flags


def _root(value: str | os.PathLike[str]) -> Path:
    try:
        path = Path(value).expanduser()
        info = path.lstat()
    except (OSError, TypeError, ValueError, RuntimeError):
        _raise(PRODUCER_ROOT_UNSAFE)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _raise(PRODUCER_ROOT_UNSAFE)
    return Path(os.path.abspath(path))


def _read_regular(
    root: Path,
    relative: str,
    *,
    limit: int,
    missing: str,
    regular: str,
    large: str,
    changed: str,
    unsafe: str,
) -> bytes:
    descriptors: list[int] = []
    try:
        root_fd = os.open(root, _open_flags(directory=True))
        descriptors.append(root_fd)
        parent_fd = root_fd
        parts = relative.split("/")
        for part in parts[:-1]:
            next_fd = os.open(part, _open_flags(directory=True), dir_fd=parent_fd)
            descriptors.append(next_fd)
            parent_fd = next_fd
        file_fd = os.open(parts[-1], _open_flags(), dir_fd=parent_fd)
        descriptors.append(file_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            _raise(regular)
        if before.st_size > limit:
            _raise(large)
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_fd)
        if len(content) > limit:
            _raise(large)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_size != len(content)
        ):
            _raise(changed)
        return content
    except ProducerHandoffError:
        raise
    except FileNotFoundError:
        _raise(missing)
    except (NotADirectoryError, PermissionError) as exc:
        if isinstance(exc, NotADirectoryError):
            _raise(unsafe)
        _raise(unsafe)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            _raise(missing)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
            _raise(unsafe)
        _raise(changed)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _parse_json(content: bytes) -> dict[str, Any]:
    if len(content) > MAX_PRODUCER_ENVELOPE_BYTES:
        _raise(PRODUCER_ENVELOPE_TOO_LARGE)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        _raise(PRODUCER_ENVELOPE_ENCODING_INVALID)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (json.JSONDecodeError, ValueError, RecursionError, _DuplicateJsonKey):
        _raise(PRODUCER_ENVELOPE_JSON_INVALID)
    if not isinstance(value, dict):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def parse_producer_envelope(value: object) -> ProducerResultEnvelope:
    """Parse one already bounded JSON object into a canonical envelope."""

    if isinstance(value, ProducerResultEnvelope):
        return value
    if isinstance(value, Mapping):
        return ProducerResultEnvelope.from_dict(dict(value))
    if isinstance(value, str):
        try:
            content = value.encode("utf-8")
        except UnicodeEncodeError:
            _raise(PRODUCER_ENVELOPE_ENCODING_INVALID)
        return ProducerResultEnvelope.from_dict(_parse_json(content))
    _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)


def declared_producer_environment_sha256() -> str:
    """Digest the generic envelope protocol declaration, without claiming host dependencies."""

    return _sha256(
        {
            "schema_version": PRODUCER_RESULT_SCHEMA_VERSION,
            "identity_kind": "declared_protocol",
            "protocol": PRODUCER_RESULT_PROTOCOL,
            "required_material_kind": PRODUCER_MATERIAL_KIND,
            "required_fields": ["path", "size", "sha256"],
            "optional_fields": ["lineage", "external_evidence"],
        }
    )


def producer_materials_sha256(envelope: ProducerResultEnvelope | Mapping[str, Any]) -> str:
    """Return the canonical pin for one envelope's material descriptors.

    This is a detached projection of the generic producer envelope.  It binds the ordered
    descriptor records (path, size, source digest, lineage and evidence summary) without reading
    a producer directory, starting an evaluator, or treating producer scores as authority.  The
    input is reparsed through the same strict DTO path used by admission so callers cannot obtain
    a pin from a mutated frozen object or a permissive mapping.
    """

    try:
        parsed = parse_producer_envelope(envelope)
        descriptors = [item.to_dict() for item in parsed.materials]
        return _sha256(descriptors)
    except ProducerHandoffError:
        raise
    except Exception:  # noqa: BLE001 - caller-supplied envelope is an untrusted boundary
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)


def producer_bundle_dependency_sha256(source_sha256s: Sequence[str]) -> str:
    """Digest the observed source set without claiming transitive dependency verification.

    ``SeedManifest`` has one dependency identity for a batch.  A producer envelope therefore uses
    this path-free, source-only bundle digest so all material records can be adjudicated in one
    manifest and receive deterministic global island/rejection handling.  The source bytes remain
    independently checked by the admission gate.
    """

    if isinstance(source_sha256s, (str, bytes)) or not isinstance(source_sha256s, Sequence):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    values = tuple(source_sha256s)
    if not 1 <= len(values) <= MAX_PRODUCER_MATERIALS:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    if any(not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None for value in values):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    return _sha256(
        {
            "schema_version": PRODUCER_RESULT_SCHEMA_VERSION,
            "identity_kind": "source_bundle_only",
            "source_sha256s": sorted(values),
            "verified_material_refs": [],
        }
    )


def _canonical_envelope(value: object) -> ProducerResultEnvelope:
    """Revalidate an object-level envelope before using any of its fields.

    ``ProducerResultEnvelope`` is frozen for ordinary callers, but Python callers can still
    deliberately bypass its constructor with ``object.__setattr__`` or provide a subclass. The
    object-level API is a trust boundary just like the JSON parser, so rebuild the DTO from its
    canonical dictionary and reject any representation that is not already canonical. This
    keeps malformed fields and custom-object exceptions inside the fixed producer error boundary.
    """

    if type(value) is not ProducerResultEnvelope:
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    try:
        raw = ProducerResultEnvelope.to_dict(value)
        canonical = ProducerResultEnvelope.from_dict(raw)
        if raw != canonical.to_dict():
            _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        return canonical
    except ProducerHandoffError:
        raise
    except Exception:  # noqa: BLE001 - object-level DTO fields are untrusted
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)


def _prepare_producer_envelope(
    external_root: str | os.PathLike[str],
    envelope: ProducerResultEnvelope,
    contract: AlgorithmProblemContract,
    *,
    evaluator_fingerprint: str,
    producer_fingerprint: str,
    producer_id: str | None = None,
    material_ref_overrides: Mapping[str, Sequence[str]] | None = None,
) -> SeedManifest:
    """Verify envelope authority and material bytes, then construct an unadmitted manifest."""

    if not isinstance(contract, AlgorithmProblemContract):
        _raise(PRODUCER_CONTRACT_MISMATCH)
    if not isinstance(envelope, ProducerResultEnvelope):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    _digest(evaluator_fingerprint, PRODUCER_EVALUATOR_FINGERPRINT_REQUIRED)
    _digest(producer_fingerprint, PRODUCER_FINGERPRINT_REQUIRED)
    if producer_id is not None:
        _identifier(producer_id, "producer_id")
    if material_ref_overrides is not None and not isinstance(material_ref_overrides, Mapping):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    envelope = _canonical_envelope(envelope)
    try:
        contract_digest = contract.digest()
    except Exception:  # noqa: BLE001 - caller-supplied contract is a trust boundary
        _raise(PRODUCER_CONTRACT_MISMATCH)
    _digest(contract_digest, PRODUCER_CONTRACT_MISMATCH)
    root = _root(external_root)
    if envelope.status != PRODUCER_COMPLETED_STATUS:
        _raise(PRODUCER_ENVELOPE_STATUS_INVALID)
    if not envelope.materials:
        _raise(PRODUCER_MATERIALS_EMPTY)
    if envelope.contract_sha256 != contract_digest:
        _raise(PRODUCER_CONTRACT_MISMATCH)
    if envelope.producer_fingerprint != producer_fingerprint or (
        producer_id is not None and envelope.producer_id != producer_id
    ):
        _raise(PRODUCER_IDENTITY_MISMATCH)

    records: list[dict[str, Any]] = []
    for material in envelope.materials:
        if material.kind != PRODUCER_MATERIAL_KIND:
            _raise(PRODUCER_MATERIAL_KIND_UNSUPPORTED)
        source = _read_regular(
            root,
            material.path,
            limit=MAX_SOURCE_BYTES,
            missing=PRODUCER_MATERIAL_MISSING,
            regular=PRODUCER_MATERIAL_NOT_REGULAR,
            large=PRODUCER_MATERIAL_TOO_LARGE,
            changed=PRODUCER_MATERIAL_CHANGED,
            unsafe=PRODUCER_MATERIAL_PATH_UNSAFE,
        )
        if len(source) != material.size:
            _raise(PRODUCER_MATERIAL_SIZE_MISMATCH)
        if hashlib.sha256(source).hexdigest() != material.sha256:
            _raise(PRODUCER_MATERIAL_DIGEST_MISMATCH)
        evidence = _merge_summaries(envelope.external_evidence, material.external_evidence)
        if material_ref_overrides is None:
            material_refs: list[str] = []
        else:
            try:
                raw_refs = material_ref_overrides.get(material.path, ())
                material_refs = _material_refs(raw_refs)
            except ProducerHandoffError:
                raise
            except Exception:  # noqa: BLE001 - adapter metadata is untrusted
                _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
        records.append(
            {
                "source_path": material.path,
                "source_sha256": material.sha256,
                "lineage": list(material.lineage),
                "provenance": {
                    "origin_kind": "external",
                    "producer_id": envelope.producer_id,
                    "producer_fingerprint": producer_fingerprint,
                    "producer_run_id": envelope.producer_run_id,
                    "material_refs": material_refs,
                    "external_evidence": evidence,
                },
                "metadata": {
                    "adapter": "generic_producer",
                    "producer_protocol": PRODUCER_RESULT_PROTOCOL,
                    "producer_envelope_sha256": envelope.envelope_sha256,
                    "producer_budget_sha256": _sha256(envelope.budget),
                },
            }
        )

    source_sha256s = [record["source_sha256"] for record in records]
    dependency_sha256 = producer_bundle_dependency_sha256(source_sha256s)
    return SeedManifest.from_dict(
        {
            "schema_version": "1",
            "contract_sha256": contract_digest,
            "evaluator": {"kind": "exact_harness", "fingerprint": evaluator_fingerprint},
            "dependency_sha256": dependency_sha256,
            "environment_sha256": declared_producer_environment_sha256(),
            "seeds": records,
        },
        source_root=root,
    )


def _admit_producer_manifest(
    manifest: SeedManifest,
    contract: AlgorithmProblemContract,
    evaluator: CandidateEvaluator,
    *,
    staging_root: str | os.PathLike[str] | None,
    num_islands: int,
) -> SeedAdmissionResult:
    return admit_seed_manifest(
        manifest,
        contract,
        evaluator,
        evaluator_kind="exact_harness",
        evaluator_fingerprint=manifest.evaluator_fingerprint,
        dependency_sha256=manifest.dependency_sha256,
        environment_sha256=manifest.environment_sha256,
        staging_root=staging_root,
        num_islands=num_islands,
    )


def admit_producer_envelope(
    external_root: str | os.PathLike[str],
    envelope: ProducerResultEnvelope,
    contract: AlgorithmProblemContract,
    evaluator: CandidateEvaluator,
    *,
    evaluator_fingerprint: str,
    producer_fingerprint: str,
    producer_id: str | None = None,
    staging_root: str | os.PathLike[str] | None = None,
    num_islands: int = 1,
    material_ref_overrides: Mapping[str, Sequence[str]] | None = None,
) -> SeedAdmissionResult:
    """Admit an already parsed producer envelope through the local evaluator.

    This is the object-level companion to :func:`admit_producer_result`.  It deliberately shares
    the same source, identity, and exact-harness checks so a transport-free adapter can construct
    an envelope without writing a second parser or a parallel score path.  ``material_ref_overrides``
    is an internal provenance projection for adapters that have an opaque reference list in
    addition to the verified source path; it never authorizes an unverified file.
    """

    # Preserve caller validation precedence before delegating envelope/material preparation.
    if not isinstance(contract, AlgorithmProblemContract):
        _raise(PRODUCER_CONTRACT_MISMATCH)
    if not callable(evaluator):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    manifest = _prepare_producer_envelope(
        external_root,
        envelope,
        contract,
        evaluator_fingerprint=evaluator_fingerprint,
        producer_fingerprint=producer_fingerprint,
        producer_id=producer_id,
        material_ref_overrides=material_ref_overrides,
    )
    return _admit_producer_manifest(
        manifest, contract, evaluator, staging_root=staging_root, num_islands=num_islands,
    )


def prepare_producer_seed_manifest(
    external_root: str | os.PathLike[str],
    contract: AlgorithmProblemContract,
    *,
    evaluator_fingerprint: str,
    producer_fingerprint: str,
    envelope_path: str | os.PathLike[str] = "producer-result.json",
    producer_id: str | None = None,
) -> SeedManifest:
    """Read completed producer material into an unadmitted in-memory seed manifest.

    The caller pins the producer identity and future local evaluator; source bytes must match
    the envelope's material hashes. Preparation does not evaluate candidates, create receipts,
    or write source material. The returned manifest retains its source root so normal seed
    admission can recheck the bytes and obtain authoritative scores from the local exact evaluator.
    """

    if not isinstance(contract, AlgorithmProblemContract):
        _raise(PRODUCER_CONTRACT_MISMATCH)
    _digest(evaluator_fingerprint, PRODUCER_EVALUATOR_FINGERPRINT_REQUIRED)
    _digest(producer_fingerprint, PRODUCER_FINGERPRINT_REQUIRED)
    if producer_id is not None:
        _identifier(producer_id, "producer_id")
    root = _root(external_root)
    relative_envelope = _relative_path(envelope_path, PRODUCER_ENVELOPE_PATH_UNSAFE)
    content = _read_regular(
        root,
        relative_envelope,
        limit=MAX_PRODUCER_ENVELOPE_BYTES,
        missing=PRODUCER_ENVELOPE_MISSING,
        regular=PRODUCER_ENVELOPE_NOT_REGULAR,
        large=PRODUCER_ENVELOPE_TOO_LARGE,
        changed=PRODUCER_ENVELOPE_JSON_INVALID,
        unsafe=PRODUCER_ENVELOPE_PATH_UNSAFE,
    )
    envelope = ProducerResultEnvelope.from_dict(_parse_json(content))
    return _prepare_producer_envelope(
        root,
        envelope,
        contract,
        evaluator_fingerprint=evaluator_fingerprint,
        producer_fingerprint=producer_fingerprint,
        producer_id=producer_id,
    )


def admit_producer_result(
    external_root: str | os.PathLike[str],
    contract: AlgorithmProblemContract,
    evaluator: CandidateEvaluator,
    *,
    evaluator_fingerprint: str,
    producer_fingerprint: str,
    envelope_path: str | os.PathLike[str] = "producer-result.json",
    producer_id: str | None = None,
    staging_root: str | os.PathLike[str] | None = None,
    num_islands: int = 1,
) -> SeedAdmissionResult:
    """Verify a producer envelope and admit its candidate materials through local evaluation.

    The producer is never called here.  ``external_root`` is only a directory containing an
    envelope and already-created material files.  A caller must pin both fingerprints separately;
    declarations inside the untrusted envelope are compared against those pins.
    """

    # A malformed evaluator must still fail before any pin validation or filesystem read.
    if not isinstance(contract, AlgorithmProblemContract):
        _raise(PRODUCER_CONTRACT_MISMATCH)
    if not callable(evaluator):
        _raise(PRODUCER_ENVELOPE_SCHEMA_INVALID)
    manifest = prepare_producer_seed_manifest(
        external_root,
        contract,
        evaluator_fingerprint=evaluator_fingerprint,
        producer_fingerprint=producer_fingerprint,
        envelope_path=envelope_path,
        producer_id=producer_id,
    )
    return _admit_producer_manifest(
        manifest, contract, evaluator, staging_root=staging_root, num_islands=num_islands,
    )


__all__ = [
    "MAX_PRODUCER_BUDGET_FIELDS",
    "MAX_PRODUCER_ENVELOPE_BYTES",
    "MAX_PRODUCER_EVIDENCE_BYTES",
    "MAX_PRODUCER_EVIDENCE_DEPTH",
    "MAX_PRODUCER_EVIDENCE_NODES",
    "MAX_PRODUCER_LINEAGE_ITEMS",
    "MAX_PRODUCER_MATERIALS",
    "MAX_PRODUCER_TOTAL_MATERIAL_BYTES",
    "PRODUCER_BUDGET_INVALID",
    "PRODUCER_COMPLETED_STATUS",
    "PRODUCER_CONTRACT_MISMATCH",
    "PRODUCER_ENVELOPE_ENCODING_INVALID",
    "PRODUCER_ENVELOPE_JSON_INVALID",
    "PRODUCER_ENVELOPE_MISSING",
    "PRODUCER_ENVELOPE_NOT_REGULAR",
    "PRODUCER_ENVELOPE_PATH_UNSAFE",
    "PRODUCER_ENVELOPE_SCHEMA_INVALID",
    "PRODUCER_ENVELOPE_STATUS_INVALID",
    "PRODUCER_ENVELOPE_TOO_LARGE",
    "PRODUCER_EVALUATOR_FINGERPRINT_REQUIRED",
    "PRODUCER_FINGERPRINT_REQUIRED",
    "PRODUCER_IDENTITY_MISMATCH",
    "PRODUCER_MATERIALS_EMPTY",
    "PRODUCER_MATERIALS_TOO_MANY",
    "PRODUCER_MATERIAL_CHANGED",
    "PRODUCER_MATERIAL_DIGEST_MISMATCH",
    "PRODUCER_MATERIAL_KIND_UNSUPPORTED",
    "PRODUCER_MATERIAL_MISSING",
    "PRODUCER_MATERIAL_NOT_REGULAR",
    "PRODUCER_MATERIAL_PATH_UNSAFE",
    "PRODUCER_MATERIAL_SIZE_MISMATCH",
    "PRODUCER_MATERIAL_TOO_LARGE",
    "PRODUCER_RESULT_PROTOCOL",
    "PRODUCER_RESULT_SCHEMA_VERSION",
    "PRODUCER_ROOT_UNSAFE",
    "ProducerHandoffError",
    "ProducerMaterial",
    "ProducerResultEnvelope",
    "admit_producer_envelope",
    "admit_producer_result",
    "declared_producer_environment_sha256",
    "parse_producer_envelope",
    "prepare_producer_seed_manifest",
    "producer_bundle_dependency_sha256",
    "producer_materials_sha256",
]
