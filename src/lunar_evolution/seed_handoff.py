"""Verified, framework-neutral admission of local seed artifacts.

External evolution engines are material producers at this boundary.  Their scores are provenance;
only the configured local evaluator can create an admission receipt. Retained admissions can be
recovered without reevaluation against a fresh manifest and an independently pinned receipt.
The adapter deliberately has no generator, backend, or network dependency.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from . import _benchmark_files as _files
from .algorithm import AlgorithmProblemContract, EvaluationReport
from .evolution import (
    MAX_ARCHIVE_LINE_BYTES,
    MAX_METADATA_BYTES,
    MAX_SOURCE_BYTES,
    Candidate,
    CandidateDraft,
    CandidateEvaluator,
    EvolutionError,
)

SEED_MANIFEST_SCHEMA_VERSION = "1"
EVALUATOR_RECEIPT_SCHEMA_VERSION = "1"
MAX_SEEDS = 32
MAX_MANIFEST_BYTES = 512 * 1024
MAX_LINEAGE_ITEMS = 64
MAX_MATERIAL_REFS = 32
MAX_EXTERNAL_EVIDENCE_ITEMS = 32
MAX_EXTERNAL_EVIDENCE_BYTES = 4 * 1024
MAX_PATH_BYTES = 1_024
MAX_REFERENCE_BYTES = 512
EXACT_HARNESS_KIND = "exact_harness"

MANIFEST_INVALID = "manifest_invalid"
MANIFEST_TOO_LARGE = "manifest_too_large"
UNKNOWN_FIELD = "unknown_field"
MISSING_FIELD = "missing_field"
UNSUPPORTED_SCHEMA = "unsupported_schema"
EMPTY_MANIFEST = "empty_manifest"
TOO_MANY_SEEDS = "too_many_seeds"
DUPLICATE_SOURCE = "duplicate_source"
DUPLICATE_IDENTITY = "duplicate_identity"
IDENTITY_COLLISION = "identity_collision"
IDENTITY_MISMATCH = "identity_mismatch"
CONTRACT_MISMATCH = "contract_mismatch"
EVALUATOR_MISMATCH = "evaluator_mismatch"
DEPENDENCY_MISMATCH = "dependency_mismatch"
ENVIRONMENT_MISMATCH = "environment_mismatch"
MANIFEST_ROOT_REQUIRED = "manifest_root_required"
SOURCE_MISSING = "source_missing"
SOURCE_UNSAFE = "source_unsafe"
SOURCE_NOT_REGULAR = "source_not_regular"
SOURCE_TOO_LARGE = "source_too_large"
SOURCE_EMPTY = "source_empty"
SOURCE_ENCODING_INVALID = "source_encoding_invalid"
SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
SOURCE_CHANGED = "source_changed"
STAGED_SOURCE_CHANGED = "staged_source_changed"
METADATA_TOO_LARGE = "metadata_too_large"
EXTERNAL_REQUIRES_EXACT_HARNESS = "external_requires_exact_harness"
EVALUATOR_FAILED = "evaluator_failed"
INVALID_EVALUATION_REPORT = "invalid_evaluation_report"
LOCAL_EVALUATION_INVALID = "local_evaluation_invalid"
LOCAL_SCORE_UNAVAILABLE = "local_score_unavailable"
EXTERNAL_SCORE_ONLY = "external_score_only"
NO_USABLE_SEEDS = "no_usable_seeds"
RETAINED_ADMISSION_MISMATCH = "retained_admission_mismatch"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token)\s*[:=]\s*\S+)"
)
_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "credential",
        "credentials",
        "error",
        "error_message",
        "exception",
        "exception_text",
        "password",
        "payload",
        "prompt",
        "remote_payload",
        "secret",
        "stderr",
        "stdout",
        "system_prompt",
        "traceback",
    }
)
_EXTERNAL_SUMMARY_FIELDS = frozenset(
    {"present", "score_present", "payload_sha256"}
)
_SCORE_KEYS = frozenset({"fitness", "quality", "reward"})


class SeedAdmissionError(RuntimeError):
    """A fixed-code handoff failure that never includes source or evaluator exception text."""

    def __init__(
        self,
        code: str,
        *,
        result: SeedAdmissionResult | None = None,
    ) -> None:
        if not isinstance(code, str) or not _KIND_RE.fullmatch(code):
            code = MANIFEST_INVALID
        self.code = code
        self.result = result
        super().__init__(code)


def _raise(code: str) -> None:
    raise SeedAdmissionError(code)


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        _raise(MANIFEST_INVALID)
    try:
        return encoded.encode("utf-8")
    except UnicodeEncodeError:
        _raise(MANIFEST_INVALID)


def _utf8_bytes(value: str, code: str = MANIFEST_INVALID) -> bytes:
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        _raise(code)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest(value: object, code: str = MANIFEST_INVALID) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _raise(code)
    return value


def _safe_id(value: object, code: str = MANIFEST_INVALID) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        _raise(code)
    if _CREDENTIAL_RE.search(value):
        _raise(code)
    return value


def _kind(value: object, code: str = MANIFEST_INVALID) -> str:
    if not isinstance(value, str) or not _KIND_RE.fullmatch(value):
        _raise(code)
    return value


def _safe_segment(value: object, code: str = MANIFEST_INVALID, *, limit: int = 512) -> str:
    if not isinstance(value, str):
        _raise(code)
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or "\x00" in normalized
        or len(_utf8_bytes(normalized, code)) > limit
        or _CREDENTIAL_RE.search(normalized)
    ):
        _raise(code)
    return normalized


def _fixed_object(
    value: object,
    *,
    allowed: frozenset[str],
    required: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _raise(MANIFEST_INVALID)
    if set(value) - allowed:
        _raise(UNKNOWN_FIELD)
    if required - set(value):
        _raise(MISSING_FIELD)
    return value


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _raise(SOURCE_UNSAFE)
    if len(_utf8_bytes(value, SOURCE_UNSAFE)) > MAX_PATH_BYTES:
        _raise(SOURCE_UNSAFE)
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _raise(SOURCE_UNSAFE)
    return path.as_posix()


def _validate_json_tree(value: object, *, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > 512 or depth > 8:
        _raise(MANIFEST_INVALID)
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _raise(MANIFEST_INVALID)
        return
    if isinstance(value, str):
        if len(_utf8_bytes(value)) > MAX_METADATA_BYTES or _CREDENTIAL_RE.search(value):
            _raise(MANIFEST_INVALID)
        return
    if isinstance(value, list):
        if len(value) > 128:
            _raise(MANIFEST_INVALID)
        for item in value:
            _validate_json_tree(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        if len(value) > 128:
            _raise(MANIFEST_INVALID)
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(_utf8_bytes(key)) > 128:
                _raise(MANIFEST_INVALID)
            if key.casefold() in _FORBIDDEN_METADATA_KEYS or _CREDENTIAL_RE.search(key):
                _raise(MANIFEST_INVALID)
            _validate_json_tree(item, depth=depth + 1, counter=counter)
        return
    _raise(MANIFEST_INVALID)


def _bounded_json_object(value: object, *, limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        _raise(MANIFEST_INVALID)
    _validate_json_tree(value)
    encoded = _canonical_bytes(value)
    if len(encoded) > limit:
        _raise(METADATA_TOO_LARGE)
    # Detach mutable input mappings and normalize them to plain JSON containers.
    return json.loads(encoded.decode("utf-8"))


def _contains_score(value: object) -> bool:
    remaining = [value]
    while remaining:
        item = remaining.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = key.casefold()
                if "score" in normalized or normalized in _SCORE_KEYS:
                    return True
                remaining.append(child)
        elif isinstance(item, list):
            remaining.extend(item)
    return False


def _external_payload_summary(value: dict[str, Any]) -> dict[str, Any]:
    """Return a stable digest-only projection of an untrusted external JSON object."""

    if set(value) == _EXTERNAL_SUMMARY_FIELDS:
        present = value["present"]
        score_present = value["score_present"]
        payload_sha256 = value["payload_sha256"]
        if not isinstance(present, bool) or not isinstance(score_present, bool):
            _raise(MANIFEST_INVALID)
        if present:
            _digest(payload_sha256)
        elif score_present or payload_sha256 is not None:
            _raise(MANIFEST_INVALID)
        return {
            "present": present,
            "score_present": score_present,
            "payload_sha256": payload_sha256,
        }

    present = bool(value)
    return {
        "present": present,
        "score_present": _contains_score(value) if present else False,
        "payload_sha256": _sha256(value) if present else None,
    }


@dataclass(frozen=True)
class EvaluatorIdentity:
    kind: str
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _kind(self.kind))
        object.__setattr__(self, "fingerprint", _digest(self.fingerprint))

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value: object) -> EvaluatorIdentity:
        raw = _fixed_object(
            value,
            allowed=frozenset({"kind", "fingerprint"}),
            required=frozenset({"kind", "fingerprint"}),
        )
        return cls(kind=raw["kind"], fingerprint=raw["fingerprint"])


@dataclass(frozen=True)
class SeedProvenance:
    origin_kind: Literal["local", "external"]
    producer_id: str
    producer_fingerprint: str
    producer_run_id: str | None = None
    material_refs: tuple[str, ...] = ()
    external_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.origin_kind not in {"local", "external"}:
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "producer_id", _safe_id(self.producer_id))
        object.__setattr__(
            self,
            "producer_fingerprint",
            _digest(self.producer_fingerprint),
        )
        if self.producer_run_id is not None:
            object.__setattr__(self, "producer_run_id", _safe_id(self.producer_run_id))
        refs = tuple(self.material_refs)
        if len(refs) > MAX_MATERIAL_REFS or len(set(refs)) != len(refs):
            _raise(MANIFEST_INVALID)
        for item in refs:
            if (
                not isinstance(item, str)
                or not item
                or len(_utf8_bytes(item)) > MAX_REFERENCE_BYTES
                or _CREDENTIAL_RE.search(item)
            ):
                _raise(MANIFEST_INVALID)
        evidence = _bounded_json_object(
            self.external_evidence,
            limit=MAX_EXTERNAL_EVIDENCE_BYTES,
        )
        if len(evidence) > MAX_EXTERNAL_EVIDENCE_ITEMS:
            _raise(MANIFEST_INVALID)
        if self.origin_kind == "external":
            evidence = _external_payload_summary(evidence)
        object.__setattr__(self, "material_refs", refs)
        object.__setattr__(self, "external_evidence", evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_kind": self.origin_kind,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "producer_run_id": self.producer_run_id,
            "material_refs": list(self.material_refs),
            "external_evidence": dict(self.external_evidence),
        }

    def digest(self) -> str:
        return _sha256(self.to_dict())

    def compact_projection(self) -> dict[str, Any]:
        return {
            "origin_kind": self.origin_kind,
            "producer_id": self.producer_id,
            "producer_fingerprint": self.producer_fingerprint,
            "producer_run_id": self.producer_run_id,
            "material_refs_sha256": _sha256(list(self.material_refs)),
            "external_evidence_sha256": _sha256(self.external_evidence),
        }

    @classmethod
    def from_dict(cls, value: object) -> SeedProvenance:
        raw = _fixed_object(
            value,
            allowed=frozenset(
                {
                    "origin_kind",
                    "producer_id",
                    "producer_fingerprint",
                    "producer_run_id",
                    "material_refs",
                    "external_evidence",
                }
            ),
            required=frozenset(
                {"origin_kind", "producer_id", "producer_fingerprint"}
            ),
        )
        run_id = raw.get("producer_run_id")
        if run_id is not None and not isinstance(run_id, str):
            _raise(MANIFEST_INVALID)
        refs = raw.get("material_refs", [])
        if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
            _raise(MANIFEST_INVALID)
        evidence = raw.get("external_evidence", {})
        if not isinstance(evidence, dict):
            _raise(MANIFEST_INVALID)
        return cls(
            origin_kind=raw["origin_kind"],
            producer_id=raw["producer_id"],
            producer_fingerprint=raw["producer_fingerprint"],
            producer_run_id=run_id,
            material_refs=tuple(refs),
            external_evidence=evidence,
        )


@dataclass(frozen=True)
class SeedRecord:
    source_path: str
    source_sha256: str
    lineage: tuple[str, ...]
    provenance: SeedProvenance
    metadata: dict[str, Any] = field(default_factory=dict)
    identity: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", _portable_path(self.source_path))
        object.__setattr__(self, "source_sha256", _digest(self.source_sha256))
        lineage = tuple(self.lineage)
        if len(lineage) > MAX_LINEAGE_ITEMS or len(set(lineage)) != len(lineage):
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "lineage", tuple(_safe_id(item) for item in lineage))
        if not isinstance(self.provenance, SeedProvenance):
            _raise(MANIFEST_INVALID)
        metadata = _bounded_json_object(self.metadata, limit=MAX_METADATA_BYTES)
        if self.provenance.origin_kind == "external":
            metadata = _external_payload_summary(metadata)
        object.__setattr__(self, "metadata", metadata)
        if self.identity is not None:
            object.__setattr__(self, "identity", _safe_id(self.identity))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "lineage": list(self.lineage),
            "provenance": self.provenance.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.identity is not None:
            result["identity"] = self.identity
        return result

    @classmethod
    def from_dict(cls, value: object) -> SeedRecord:
        raw = _fixed_object(
            value,
            allowed=frozenset(
                {
                    "identity",
                    "source_path",
                    "source_sha256",
                    "lineage",
                    "provenance",
                    "metadata",
                }
            ),
            required=frozenset(
                {"source_path", "source_sha256", "lineage", "provenance"}
            ),
        )
        identity = raw.get("identity")
        if identity is not None and not isinstance(identity, str):
            _raise(MANIFEST_INVALID)
        lineage = raw["lineage"]
        if not isinstance(lineage, list) or any(not isinstance(item, str) for item in lineage):
            _raise(MANIFEST_INVALID)
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            _raise(MANIFEST_INVALID)
        return cls(
            identity=identity,
            source_path=raw["source_path"],
            source_sha256=raw["source_sha256"],
            lineage=tuple(lineage),
            provenance=SeedProvenance.from_dict(raw["provenance"]),
            metadata=metadata,
        )


@dataclass(frozen=True)
class SeedIdentity:
    source_sha256: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    lineage: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "source_sha256",
            "contract_sha256",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name)))
        object.__setattr__(self, "evaluator_kind", _kind(self.evaluator_kind))
        lineage = tuple(self.lineage)
        if len(lineage) > MAX_LINEAGE_ITEMS or len(set(lineage)) != len(lineage):
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "lineage", tuple(_safe_id(item) for item in lineage))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEED_MANIFEST_SCHEMA_VERSION,
            "source_sha256": self.source_sha256,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "lineage": list(self.lineage),
        }

    @property
    def digest(self) -> str:
        return _sha256(self.to_dict())

    @property
    def candidate_id(self) -> str:
        return f"seed-{self.digest}"


@dataclass(frozen=True)
class SeedManifest:
    schema_version: str
    contract_sha256: str
    evaluator: EvaluatorIdentity
    dependency_sha256: str
    environment_sha256: str
    seeds: tuple[SeedRecord, ...]
    _source_root: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema_version != SEED_MANIFEST_SCHEMA_VERSION:
            _raise(UNSUPPORTED_SCHEMA)
        object.__setattr__(self, "contract_sha256", _digest(self.contract_sha256))
        if not isinstance(self.evaluator, EvaluatorIdentity):
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "dependency_sha256", _digest(self.dependency_sha256))
        object.__setattr__(self, "environment_sha256", _digest(self.environment_sha256))
        seeds = tuple(self.seeds)
        if not seeds:
            _raise(EMPTY_MANIFEST)
        if len(seeds) > MAX_SEEDS:
            _raise(TOO_MANY_SEEDS)
        if any(not isinstance(seed, SeedRecord) for seed in seeds):
            _raise(MANIFEST_INVALID)
        paths = [seed.source_path for seed in seeds]
        if len(paths) != len(set(paths)):
            _raise(DUPLICATE_SOURCE)
        object.__setattr__(self, "seeds", seeds)
        if self._source_root is not None:
            object.__setattr__(self, "_source_root", _source_root(self._source_root))

        identities: dict[str, SeedIdentity] = {}
        declared_identities: dict[str, SeedIdentity] = {}
        for seed in seeds:
            material = seed_identity_material(seed, self)
            candidate_id = material.candidate_id
            if seed.identity is not None:
                previous_claim = declared_identities.get(seed.identity)
                if previous_claim is not None and previous_claim.to_dict() != material.to_dict():
                    _raise(IDENTITY_COLLISION)
                declared_identities[seed.identity] = material
            if seed.identity is not None and seed.identity != candidate_id:
                _raise(IDENTITY_MISMATCH)
            previous = identities.get(candidate_id)
            if previous is not None:
                if previous.to_dict() != material.to_dict():
                    _raise(DUPLICATE_IDENTITY)
                _raise(DUPLICATE_IDENTITY)
            identities[candidate_id] = material

    @property
    def source_root(self) -> Path | None:
        return self._source_root

    @property
    def evaluator_kind(self) -> str:
        return self.evaluator.kind

    @property
    def evaluator_fingerprint(self) -> str:
        return self.evaluator.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_sha256": self.contract_sha256,
            "evaluator": self.evaluator.to_dict(),
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "seeds": [seed.to_dict() for seed in self.seeds],
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        source_root: str | os.PathLike[str] | None = None,
    ) -> SeedManifest:
        raw = _fixed_object(
            value,
            allowed=frozenset(
                {
                    "schema_version",
                    "contract_sha256",
                    "evaluator",
                    "dependency_sha256",
                    "environment_sha256",
                    "seeds",
                }
            ),
            required=frozenset(
                {
                    "schema_version",
                    "contract_sha256",
                    "evaluator",
                    "dependency_sha256",
                    "environment_sha256",
                    "seeds",
                }
            ),
        )
        seeds = raw["seeds"]
        if not isinstance(seeds, list):
            _raise(MANIFEST_INVALID)
        return cls(
            schema_version=raw["schema_version"],
            contract_sha256=raw["contract_sha256"],
            evaluator=EvaluatorIdentity.from_dict(raw["evaluator"]),
            dependency_sha256=raw["dependency_sha256"],
            environment_sha256=raw["environment_sha256"],
            seeds=tuple(SeedRecord.from_dict(item) for item in seeds),
            _source_root=Path(source_root) if source_root is not None else None,
        )

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> SeedManifest:
        return _manifest_from_path(Path(path))


def seed_identity_material(seed: SeedRecord, manifest: SeedManifest) -> SeedIdentity:
    if not isinstance(seed, SeedRecord) or not isinstance(manifest, SeedManifest):
        _raise(MANIFEST_INVALID)
    return SeedIdentity(
        source_sha256=seed.source_sha256,
        contract_sha256=manifest.contract_sha256,
        evaluator_kind=manifest.evaluator.kind,
        evaluator_fingerprint=manifest.evaluator.fingerprint,
        dependency_sha256=manifest.dependency_sha256,
        environment_sha256=manifest.environment_sha256,
        lineage=seed.lineage,
    )


def compute_seed_identity(seed: SeedRecord, manifest: SeedManifest) -> str:
    """Return the stable population candidate ID for one manifest record."""

    return seed_identity_material(seed, manifest).candidate_id


def compute_handoff_fingerprint(candidate_id: str, provenance: SeedProvenance) -> str:
    """Bind stable candidate identity to normalized producer provenance for resume checks."""

    candidate_id = _safe_id(candidate_id)
    if not isinstance(provenance, SeedProvenance):
        _raise(MANIFEST_INVALID)
    return _sha256(
        {
            "schema_version": SEED_MANIFEST_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "provenance": provenance.to_dict(),
        }
    )


@dataclass(frozen=True)
class EvaluatorReceipt:
    schema_version: str
    candidate_id: str
    source_sha256: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    report_schema_version: str
    evaluator_id: str
    validity: int
    quality: float | None
    combined_score: float
    detailed_scores: dict[str, dict[str, Any]]
    error_info: tuple[dict[str, str], ...]
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != EVALUATOR_RECEIPT_SCHEMA_VERSION:
            _raise(INVALID_EVALUATION_REPORT)
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id))
        for name in (
            "source_sha256",
            "contract_sha256",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "receipt_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), INVALID_EVALUATION_REPORT))
        object.__setattr__(
            self,
            "evaluator_kind",
            _kind(self.evaluator_kind, INVALID_EVALUATION_REPORT),
        )
        evaluator_id = _safe_segment(self.evaluator_id, INVALID_EVALUATION_REPORT, limit=512)
        object.__setattr__(self, "evaluator_id", evaluator_id)
        if self.report_schema_version != "1":
            _raise(INVALID_EVALUATION_REPORT)
        if self.validity not in {0, 1} or isinstance(self.validity, bool):
            _raise(INVALID_EVALUATION_REPORT)
        if not _finite_non_negative(self.combined_score):
            _raise(INVALID_EVALUATION_REPORT)
        object.__setattr__(self, "combined_score", float(self.combined_score))
        if self.validity == 0 and self.combined_score != 0:
            _raise(INVALID_EVALUATION_REPORT)
        if self.quality is not None:
            if not _finite_non_negative(self.quality):
                _raise(INVALID_EVALUATION_REPORT)
            object.__setattr__(self, "quality", float(self.quality))
        details = _normalized_detailed_scores(self.detailed_scores)
        errors = _normalized_receipt_errors(self.error_info)
        if self.validity == 0 and not errors:
            _raise(INVALID_EVALUATION_REPORT)
        object.__setattr__(self, "detailed_scores", details)
        object.__setattr__(self, "error_info", errors)
        if self.receipt_sha256 != _sha256(self.canonical_payload()):
            _raise(INVALID_EVALUATION_REPORT)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "source_sha256": self.source_sha256,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "report_schema_version": self.report_schema_version,
            "evaluator_id": self.evaluator_id,
            "validity": self.validity,
            "quality": self.quality,
            "combined_score": self.combined_score,
            "detailed_scores": self.detailed_scores,
            "error_info": list(self.error_info),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_report(
        cls,
        report: EvaluationReport,
        *,
        candidate_id: str,
        source_sha256: str,
        contract_sha256: str,
        evaluator_kind: str,
        evaluator_fingerprint: str,
        dependency_sha256: str,
        environment_sha256: str,
    ) -> EvaluatorReceipt:
        if not isinstance(report, EvaluationReport):
            _raise(INVALID_EVALUATION_REPORT)
        details = _normalized_detailed_scores(report.detailed_scores)
        errors = _normalized_receipt_errors(report.error_info)
        payload = {
            "schema_version": EVALUATOR_RECEIPT_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "source_sha256": source_sha256,
            "contract_sha256": contract_sha256,
            "evaluator_kind": evaluator_kind,
            "evaluator_fingerprint": evaluator_fingerprint,
            "dependency_sha256": dependency_sha256,
            "environment_sha256": environment_sha256,
            "report_schema_version": report.schema_version,
            "evaluator_id": report.evaluator_id,
            "validity": report.validity,
            "quality": float(report.quality) if report.quality is not None else None,
            "combined_score": float(report.combined_score),
            "detailed_scores": details,
            "error_info": list(errors),
        }
        constructor = {**payload, "error_info": errors, "receipt_sha256": _sha256(payload)}
        return cls(**constructor)

    @classmethod
    def from_dict(cls, value: object) -> EvaluatorReceipt:
        fields = frozenset(
            {
                "schema_version",
                "candidate_id",
                "source_sha256",
                "contract_sha256",
                "evaluator_kind",
                "evaluator_fingerprint",
                "dependency_sha256",
                "environment_sha256",
                "report_schema_version",
                "evaluator_id",
                "validity",
                "quality",
                "combined_score",
                "detailed_scores",
                "error_info",
                "receipt_sha256",
            }
        )
        raw = _fixed_object(value, allowed=fields, required=fields)
        errors = raw["error_info"]
        if not isinstance(errors, list):
            _raise(INVALID_EVALUATION_REPORT)
        return cls(
            schema_version=raw["schema_version"],
            candidate_id=raw["candidate_id"],
            source_sha256=raw["source_sha256"],
            contract_sha256=raw["contract_sha256"],
            evaluator_kind=raw["evaluator_kind"],
            evaluator_fingerprint=raw["evaluator_fingerprint"],
            dependency_sha256=raw["dependency_sha256"],
            environment_sha256=raw["environment_sha256"],
            report_schema_version=raw["report_schema_version"],
            evaluator_id=raw["evaluator_id"],
            validity=raw["validity"],
            quality=raw["quality"],
            combined_score=raw["combined_score"],
            detailed_scores=raw["detailed_scores"],
            error_info=tuple(errors),
            receipt_sha256=raw["receipt_sha256"],
        )


def _finite_non_negative(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _normalized_detailed_scores(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(value) > 32:
        _raise(INVALID_EVALUATION_REPORT)
    result: dict[str, dict[str, Any]] = {}
    for name, item in value.items():
        name = _safe_segment(name, INVALID_EVALUATION_REPORT, limit=512)
        if not isinstance(item, dict) or set(item) != {"value", "direction"}:
            _raise(INVALID_EVALUATION_REPORT)
        score = item["value"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            _raise(INVALID_EVALUATION_REPORT)
        if item["direction"] not in {"maximize", "minimize"}:
            _raise(INVALID_EVALUATION_REPORT)
        result[name] = {"value": float(score), "direction": item["direction"]}
    return result


def _normalized_receipt_errors(value: Sequence[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        _raise(INVALID_EVALUATION_REPORT)
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"code", "message"}:
            _raise(INVALID_EVALUATION_REPORT)
        code = _safe_segment(item.get("code"), INVALID_EVALUATION_REPORT, limit=128)
        # Evaluator prose is deliberately not copied into persistent handoff evidence.
        result.append({"code": code, "message": "local evaluator reported an error"})
    return tuple(result)


@dataclass(frozen=True)
class RejectedSeed:
    index: int
    source_path: str
    identity: str
    code: str

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "source_path", _portable_path(self.source_path))
        object.__setattr__(self, "identity", _safe_id(self.identity))
        object.__setattr__(self, "code", _kind(self.code))

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source_path": self.source_path,
            "identity": self.identity,
            "code": self.code,
        }


@dataclass(frozen=True)
class AdmittedSeed:
    candidate_id: str
    draft: CandidateDraft
    evaluation: EvaluationReport
    receipt: EvaluatorReceipt
    provenance: SeedProvenance
    handoff_sha256: str
    generation: int = 0
    iteration: int = 0
    parent_id: None = None
    strategy: Literal["population"] = "population"
    island_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _safe_id(self.candidate_id))
        if not isinstance(self.draft, CandidateDraft):
            _raise(MANIFEST_INVALID)
        if not isinstance(self.evaluation, EvaluationReport):
            _raise(INVALID_EVALUATION_REPORT)
        if not isinstance(self.receipt, EvaluatorReceipt):
            _raise(INVALID_EVALUATION_REPORT)
        if not isinstance(self.provenance, SeedProvenance):
            _raise(MANIFEST_INVALID)
        object.__setattr__(self, "handoff_sha256", _digest(self.handoff_sha256))
        if self.receipt.candidate_id != self.candidate_id:
            _raise(INVALID_EVALUATION_REPORT)
        if self.handoff_sha256 != compute_handoff_fingerprint(
            self.candidate_id,
            self.provenance,
        ):
            _raise(MANIFEST_INVALID)
        if self.generation != 0 or self.iteration != 0 or self.parent_id is not None:
            _raise(MANIFEST_INVALID)
        if self.strategy != "population":
            _raise(MANIFEST_INVALID)
        if (
            isinstance(self.island_id, bool)
            or not isinstance(self.island_id, int)
            or self.island_id < 0
        ):
            _raise(MANIFEST_INVALID)

    def candidate_fields(self) -> dict[str, Any]:
        """Return deterministic fields for a later archive/population transaction."""

        return {
            "candidate_id": self.candidate_id,
            "parent_id": None,
            "generation": 0,
            "iteration": 0,
            "strategy": "population",
            "island_id": self.island_id,
            "evaluation": self.evaluation,
            "metadata": self.draft.metadata,
        }


@dataclass(frozen=True)
class SeedAdmissionResult:
    admitted: tuple[AdmittedSeed, ...]
    rejected: tuple[RejectedSeed, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(item, AdmittedSeed) for item in self.admitted):
            _raise(MANIFEST_INVALID)
        if any(not isinstance(item, RejectedSeed) for item in self.rejected):
            _raise(MANIFEST_INVALID)

    @property
    def usable_count(self) -> int:
        return len(self.admitted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": [
                {
                    **item.candidate_fields(),
                    "evaluation": item.evaluation.to_dict(),
                    "receipt": item.receipt.to_dict(),
                    "handoff_sha256": item.handoff_sha256,
                }
                for item in self.admitted
            ],
            "rejected": [item.to_dict() for item in self.rejected],
        }


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _parse_json_bytes(content: bytes) -> object:
    if len(content) > MAX_MANIFEST_BYTES:
        _raise(MANIFEST_TOO_LARGE)
    try:
        text = content.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        _DuplicateJsonKey,
        RecursionError,
    ):
        _raise(MANIFEST_INVALID)


def _source_root(value: str | os.PathLike[str]) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        _raise(SOURCE_UNSAFE)
    try:
        root = raw.resolve(strict=True)
    except OSError:
        _raise(SOURCE_MISSING)
    if not root.is_dir():
        _raise(SOURCE_UNSAFE)
    return root


def _manifest_from_path(path: Path) -> SeedManifest:
    raw = path.expanduser()
    if raw.is_symlink():
        _raise(SOURCE_UNSAFE)
    descriptor: int | None = None
    try:
        descriptor = os.open(raw, _open_flags())
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _raise(MANIFEST_INVALID)
        if before.st_size > MAX_MANIFEST_BYTES:
            _raise(MANIFEST_TOO_LARGE)
        chunks: list[bytes] = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(content) > MAX_MANIFEST_BYTES:
            _raise(MANIFEST_TOO_LARGE)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_size != len(content)
        ):
            _raise(MANIFEST_INVALID)
    except OSError:
        _raise(MANIFEST_INVALID)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    value = _parse_json_bytes(content)
    return SeedManifest.from_dict(value, source_root=raw.parent)


def parse_seed_manifest(
    value: SeedManifest | Mapping[str, Any] | str | os.PathLike[str],
    *,
    source_root: str | os.PathLike[str] | None = None,
) -> SeedManifest:
    """Parse a strict manifest from a path, JSON text, or dictionary."""

    if isinstance(value, SeedManifest):
        if source_root is None:
            return value
        return SeedManifest.from_dict(value.to_dict(), source_root=source_root)
    if isinstance(value, Mapping):
        return SeedManifest.from_dict(dict(value), source_root=source_root)
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            _raise(MANIFEST_INVALID)
        parsed = _parse_json_bytes(encoded)
        return SeedManifest.from_dict(parsed, source_root=source_root)
    if isinstance(value, (str, os.PathLike)):
        manifest = _manifest_from_path(Path(value))
        if source_root is not None:
            return SeedManifest.from_dict(manifest.to_dict(), source_root=source_root)
        return manifest
    _raise(MANIFEST_INVALID)


@dataclass(frozen=True)
class _SourceSnapshot:
    content: bytes
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    def unchanged_from(self, other: _SourceSnapshot) -> bool:
        return (
            self.sha256 == other.sha256
            and self.content == other.content
            and self.device == other.device
            and self.inode == other.inode
            and self.size == other.size
            and self.mtime_ns == other.mtime_ns
            and self.ctime_ns == other.ctime_ns
        )


def _open_flags(*, directory: bool = False) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return flags


def _safe_source_snapshot(root: Path, relative: str) -> _SourceSnapshot:
    parts = relative.split("/")
    descriptors: list[int] = []
    try:
        root_fd = os.open(root, _open_flags(directory=True))
        descriptors.append(root_fd)
        parent_fd = root_fd
        for part in parts[:-1]:
            next_fd = os.open(part, _open_flags(directory=True), dir_fd=parent_fd)
            descriptors.append(next_fd)
            parent_fd = next_fd
        file_fd = os.open(parts[-1], _open_flags(), dir_fd=parent_fd)
        descriptors.append(file_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            _raise(SOURCE_NOT_REGULAR)
        if before.st_size > MAX_SOURCE_BYTES:
            _raise(SOURCE_TOO_LARGE)
        chunks: list[bytes] = []
        remaining = MAX_SOURCE_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_fd)
        if len(content) > MAX_SOURCE_BYTES:
            _raise(SOURCE_TOO_LARGE)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_size != len(content)
        ):
            _raise(SOURCE_CHANGED)
        return _SourceSnapshot(
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            device=after.st_dev,
            inode=after.st_ino,
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            ctime_ns=after.st_ctime_ns,
        )
    except SeedAdmissionError:
        raise
    except FileNotFoundError:
        _raise(SOURCE_MISSING)
    except NotADirectoryError:
        _raise(SOURCE_UNSAFE)
    except PermissionError:
        _raise(SOURCE_UNSAFE)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            _raise(SOURCE_MISSING)
        _raise(SOURCE_UNSAFE)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _stage_source(directory: Path, seed: SeedRecord, snapshot: _SourceSnapshot) -> tuple[Path, _SourceSnapshot]:
    candidate_dir = directory / hashlib.sha256(seed.source_path.encode("utf-8")).hexdigest()
    candidate_dir.mkdir(mode=0o700)
    filename = Path(seed.source_path).name
    target = candidate_dir / filename
    temporary = candidate_dir / ".source.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(snapshot.content)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    staged = _safe_source_snapshot(candidate_dir, filename)
    if staged.content != snapshot.content or staged.sha256 != snapshot.sha256:
        _raise(STAGED_SOURCE_CHANGED)
    return target, staged


def _has_external_score(seed: SeedRecord) -> bool:
    return bool(seed.provenance.external_evidence.get("score_present", False))


def _evaluation_report(value: object, seed: SeedRecord) -> EvaluationReport:
    if isinstance(value, EvaluationReport):
        return value
    if not isinstance(value, dict):
        if seed.provenance.origin_kind == "external" and _has_external_score(seed):
            _raise(EXTERNAL_SCORE_ONLY)
        _raise(INVALID_EVALUATION_REPORT)
    allowed = {
        "schema_version",
        "evaluator_id",
        "validity",
        "quality",
        "combined_score",
        "detailed_scores",
        "error_info",
    }
    if set(value) - allowed:
        _raise(INVALID_EVALUATION_REPORT)
    score = value.get("combined_score")
    if (
        score is None
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
    ):
        _raise(LOCAL_SCORE_UNAVAILABLE)
    try:
        return EvaluationReport.from_dict(value)
    except (TypeError, ValueError):
        _raise(INVALID_EVALUATION_REPORT)


def _candidate_metadata(
    seed: SeedRecord,
    manifest: SeedManifest,
    *,
    candidate_id: str,
    receipt: EvaluatorReceipt,
    handoff_sha256: str,
) -> dict[str, Any]:
    metadata = {
        "seed_handoff": {
            "schema_version": SEED_MANIFEST_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "source_sha256": seed.source_sha256,
            "contract_sha256": manifest.contract_sha256,
            "evaluator_kind": manifest.evaluator.kind,
            "evaluator_fingerprint": manifest.evaluator.fingerprint,
            "dependency_sha256": manifest.dependency_sha256,
            "environment_sha256": manifest.environment_sha256,
            "lineage": list(seed.lineage),
            "provenance": seed.provenance.compact_projection(),
            "provenance_sha256": seed.provenance.digest(),
            "handoff_sha256": handoff_sha256,
            "receipt_sha256": receipt.receipt_sha256,
        },
        "seed_metadata": dict(seed.metadata),
    }
    if len(_canonical_bytes(metadata)) > MAX_METADATA_BYTES:
        _raise(METADATA_TOO_LARGE)
    return metadata


def _recheck_snapshot(root: Path, seed: SeedRecord, before: _SourceSnapshot) -> None:
    try:
        after = _safe_source_snapshot(root, seed.source_path)
    except SeedAdmissionError:
        _raise(SOURCE_CHANGED)
    if not before.unchanged_from(after):
        _raise(SOURCE_CHANGED)


def _recheck_staged(
    candidate_dir: Path,
    filename: str,
    before: _SourceSnapshot,
) -> None:
    try:
        after = _safe_source_snapshot(candidate_dir, filename)
    except SeedAdmissionError:
        _raise(STAGED_SOURCE_CHANGED)
    if not before.unchanged_from(after):
        _raise(STAGED_SOURCE_CHANGED)


def _adjudicate_seed(
    *,
    index: int,
    seed: SeedRecord,
    manifest: SeedManifest,
    contract: AlgorithmProblemContract,
    source_root: Path,
    stage_root: Path,
    evaluator: CandidateEvaluator,
) -> AdmittedSeed:
    del index
    candidate_id = compute_seed_identity(seed, manifest)
    if seed.provenance.origin_kind == "external" and manifest.evaluator.kind != EXACT_HARNESS_KIND:
        _raise(EXTERNAL_REQUIRES_EXACT_HARNESS)

    original = _safe_source_snapshot(source_root, seed.source_path)
    if original.sha256 != seed.source_sha256:
        _raise(SOURCE_DIGEST_MISMATCH)
    if not original.content:
        _raise(SOURCE_EMPTY)
    try:
        source_text = original.content.decode("utf-8")
    except UnicodeDecodeError:
        _raise(SOURCE_ENCODING_INVALID)
    if not source_text.strip():
        _raise(SOURCE_EMPTY)

    staged_path, staged_before = _stage_source(stage_root, seed, original)
    evaluation_output: object = None
    evaluator_failed = False
    try:
        evaluation_output = evaluator(staged_path, contract)
    except Exception:  # noqa: BLE001 - arbitrary injected evaluators must not cross the boundary
        evaluator_failed = True

    _recheck_staged(staged_path.parent, staged_path.name, staged_before)
    _recheck_snapshot(source_root, seed, original)
    if evaluator_failed:
        _raise(EVALUATOR_FAILED)
    report = _evaluation_report(evaluation_output, seed)
    if report.validity != 1:
        _raise(LOCAL_EVALUATION_INVALID)
    if report.error_info:
        _raise(INVALID_EVALUATION_REPORT)
    if not _finite_non_negative(report.combined_score):
        _raise(LOCAL_SCORE_UNAVAILABLE)

    receipt = EvaluatorReceipt.from_report(
        report,
        candidate_id=candidate_id,
        source_sha256=seed.source_sha256,
        contract_sha256=manifest.contract_sha256,
        evaluator_kind=manifest.evaluator.kind,
        evaluator_fingerprint=manifest.evaluator.fingerprint,
        dependency_sha256=manifest.dependency_sha256,
        environment_sha256=manifest.environment_sha256,
    )
    handoff_sha256 = compute_handoff_fingerprint(candidate_id, seed.provenance)
    metadata = _candidate_metadata(
        seed,
        manifest,
        candidate_id=candidate_id,
        receipt=receipt,
        handoff_sha256=handoff_sha256,
    )
    try:
        draft = CandidateDraft(
            source=source_text,
            filename=Path(seed.source_path).name,
            metadata=metadata,
        )
    except EvolutionError:
        _raise(METADATA_TOO_LARGE)
    return AdmittedSeed(
        candidate_id=candidate_id,
        draft=draft,
        evaluation=report,
        receipt=receipt,
        provenance=seed.provenance,
        handoff_sha256=handoff_sha256,
    )


def _retained_seed_snapshot(root: Path, name: str, maximum: int) -> _SourceSnapshot:
    """Bind a retained file to its bytes and inode without following ancestor symlinks."""
    content = _files.read_regular_file(root / name, maximum)
    snapshot = _safe_source_snapshot(root, name)
    if snapshot.content != content:
        _raise(RETAINED_ADMISSION_MISMATCH)
    return snapshot


def recover_retained_seed_admission(
    manifest: SeedManifest,
    candidate: Candidate,
    *,
    candidate_root: str | os.PathLike[str],
    expected_receipt_sha256: str,
) -> AdmittedSeed:
    """Recover one published admission without evaluating, staging, or writing files.

    ``manifest`` must come from freshly recovered producer material with caller-pinned authority.
    ``expected_receipt_sha256`` must come from a separate retained local admission checkpoint,
    never from the receipt being inspected. The manifest binds the source, evaluator identities,
    lineage, metadata, and provenance; the receipt pin binds the original local evaluation.

    This verifies only the candidate's source, record and receipt. Callers must separately verify
    their publication transaction, for example with ``CandidateArchive.validate_initial_seeds``.
    Both population and OpenEvolve canonical seed records return the neutral population seed DTO.
    """
    try:
        if not isinstance(manifest, SeedManifest) or not isinstance(candidate, Candidate):
            _raise(RETAINED_ADMISSION_MISMATCH)
        # Detach mutable mappings before computing expected authority and metadata.
        manifest = SeedManifest.from_dict(manifest.to_dict())
        candidate = Candidate.from_dict(json.loads(_canonical_bytes(candidate.to_dict())))
        if len(manifest.seeds) != 1:
            _raise(RETAINED_ADMISSION_MISMATCH)
        receipt_pin = _digest(expected_receipt_sha256, RETAINED_ADMISSION_MISMATCH)
        seed = manifest.seeds[0]
        candidate_id = compute_seed_identity(seed, manifest)
        filename = Path(seed.source_path).name
        if (
            candidate.candidate_id != candidate_id
            or filename in {"record.json", "receipt.json"}
            or candidate.code_path != f"evolution/candidates/{candidate_id}/{filename}"
            or candidate.parent_id is not None
            or candidate.generation != 0
            or candidate.source_sha256 is not None
            or candidate.receipt_sha256 is not None
            or candidate.integrity is not None
            or candidate.bundle_evidence is not None
            or candidate.strategy not in {"population", "openevolve"}
            or (candidate.strategy == "population" and (
                candidate.iteration != 0 or candidate.island_id is None
            ))
            or (candidate.strategy == "openevolve" and (
                candidate.iteration != 1 or candidate.island_id is not None
            ))
            or (seed.provenance.origin_kind == "external"
                and manifest.evaluator.kind != EXACT_HARNESS_KIND)
        ):
            _raise(RETAINED_ADMISSION_MISMATCH)
        root = _files.absolute_path(candidate_root)
        if root.name != candidate_id:
            _raise(RETAINED_ADMISSION_MISMATCH)
        limits = {
            filename: MAX_SOURCE_BYTES,
            "receipt.json": MAX_ARCHIVE_LINE_BYTES,
            "record.json": MAX_ARCHIVE_LINE_BYTES,
        }
        snapshots = {
            name: _retained_seed_snapshot(root, name, maximum)
            for name, maximum in limits.items()
        }
        source = snapshots[filename]
        if source.sha256 != seed.source_sha256 or not source.content:
            _raise(RETAINED_ADMISSION_MISMATCH)
        source_text = source.content.decode("utf-8")
        if not source_text.strip():
            _raise(RETAINED_ADMISSION_MISMATCH)
        receipt = EvaluatorReceipt.from_dict(
            _parse_json_bytes(snapshots["receipt.json"].content)
        )
        if receipt.receipt_sha256 != receipt_pin:
            _raise(RETAINED_ADMISSION_MISMATCH)
        expected_receipt = EvaluatorReceipt.from_report(
            candidate.evaluation,
            candidate_id=candidate_id,
            source_sha256=seed.source_sha256,
            contract_sha256=manifest.contract_sha256,
            evaluator_kind=manifest.evaluator.kind,
            evaluator_fingerprint=manifest.evaluator.fingerprint,
            dependency_sha256=manifest.dependency_sha256,
            environment_sha256=manifest.environment_sha256,
        )
        if (
            receipt.validity != 1
            or receipt.error_info
            or _canonical_bytes(receipt.to_dict())
            != _canonical_bytes(expected_receipt.to_dict())
        ):
            _raise(RETAINED_ADMISSION_MISMATCH)
        handoff_sha256 = compute_handoff_fingerprint(candidate_id, seed.provenance)
        metadata = _candidate_metadata(
            seed, manifest, candidate_id=candidate_id,
            receipt=receipt, handoff_sha256=handoff_sha256,
        )
        if _canonical_bytes(candidate.metadata) != _canonical_bytes(metadata):
            _raise(RETAINED_ADMISSION_MISMATCH)
        expected_record = {
            **candidate.to_dict(),
            "seed_handoff_evidence": {
                "schema_version": SEED_MANIFEST_SCHEMA_VERSION,
                "provenance": seed.provenance.compact_projection(),
                "external_evidence": dict(seed.provenance.external_evidence),
                "provenance_sha256": seed.provenance.digest(),
                "handoff_sha256": handoff_sha256,
                "receipt_sha256": receipt.receipt_sha256,
            },
        }
        record = _parse_json_bytes(snapshots["record.json"].content)
        if _canonical_bytes(record) != _canonical_bytes(expected_record):
            _raise(RETAINED_ADMISSION_MISMATCH)
        recovered = AdmittedSeed(
            candidate_id=candidate_id,
            draft=CandidateDraft(source=source_text, filename=filename, metadata=metadata),
            evaluation=candidate.evaluation,
            receipt=receipt,
            provenance=seed.provenance,
            handoff_sha256=handoff_sha256,
            island_id=candidate.island_id if candidate.strategy == "population" else 0,
        )
        for name, before in snapshots.items():
            after = _retained_seed_snapshot(root, name, limits[name])
            if not before.unchanged_from(after):
                _raise(RETAINED_ADMISSION_MISMATCH)
        return recovered
    except (SeedAdmissionError, ValueError, TypeError, OSError, AttributeError) as exc:
        if isinstance(exc, SeedAdmissionError) and exc.code == RETAINED_ADMISSION_MISMATCH:
            raise
        raise SeedAdmissionError(RETAINED_ADMISSION_MISMATCH) from exc


def admit_seed_manifest(
    manifest_value: SeedManifest | Mapping[str, Any] | str | os.PathLike[str],
    contract: AlgorithmProblemContract,
    evaluator: CandidateEvaluator,
    *,
    evaluator_kind: str,
    evaluator_fingerprint: str,
    dependency_sha256: str,
    environment_sha256: str,
    manifest_root: str | os.PathLike[str] | None = None,
    staging_root: str | os.PathLike[str] | None = None,
    num_islands: int = 1,
) -> SeedAdmissionResult:
    """Adjudicate all records privately and return only freshly verified local seeds.

    The function has no population mutation or generator/backend hooks.  If no record is usable it
    raises :class:`SeedAdmissionError` with ``code == "no_usable_seeds"`` and attaches the bounded
    adjudication result to ``error.result``.
    """

    if not isinstance(contract, AlgorithmProblemContract):
        _raise(MANIFEST_INVALID)
    if not callable(evaluator):
        _raise(MANIFEST_INVALID)
    if (
        isinstance(num_islands, bool)
        or not isinstance(num_islands, int)
        or not 1 <= num_islands <= 64
    ):
        _raise(MANIFEST_INVALID)

    manifest = parse_seed_manifest(manifest_value, source_root=manifest_root)
    current_kind = _kind(evaluator_kind, EVALUATOR_MISMATCH)
    current_fingerprint = _digest(evaluator_fingerprint, EVALUATOR_MISMATCH)
    current_dependency = _digest(dependency_sha256, DEPENDENCY_MISMATCH)
    current_environment = _digest(environment_sha256, ENVIRONMENT_MISMATCH)
    if manifest.contract_sha256 != contract.digest():
        _raise(CONTRACT_MISMATCH)
    if (
        manifest.evaluator.kind != current_kind
        or manifest.evaluator.fingerprint != current_fingerprint
    ):
        _raise(EVALUATOR_MISMATCH)
    if manifest.dependency_sha256 != current_dependency:
        _raise(DEPENDENCY_MISMATCH)
    if manifest.environment_sha256 != current_environment:
        _raise(ENVIRONMENT_MISMATCH)
    source_root_value = manifest.source_root
    if source_root_value is None:
        _raise(MANIFEST_ROOT_REQUIRED)
    source_root = _source_root(source_root_value)

    temporary_parent: str | None = None
    if staging_root is not None:
        raw_staging_root = Path(staging_root).expanduser()
        if raw_staging_root.is_symlink():
            _raise(SOURCE_UNSAFE)
        try:
            raw_staging_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            _raise(SOURCE_UNSAFE)
        if not raw_staging_root.is_dir():
            _raise(SOURCE_UNSAFE)
        temporary_parent = str(raw_staging_root.resolve())

    admitted_unassigned: list[AdmittedSeed] = []
    rejected: list[RejectedSeed] = []
    with tempfile.TemporaryDirectory(
        prefix=".seed-handoff-",
        dir=temporary_parent,
    ) as temporary:
        private_root = Path(temporary)
        os.chmod(private_root, 0o700)
        for index, seed in enumerate(manifest.seeds):
            candidate_id = compute_seed_identity(seed, manifest)
            try:
                admitted_unassigned.append(
                    _adjudicate_seed(
                        index=index,
                        seed=seed,
                        manifest=manifest,
                        contract=contract,
                        source_root=source_root,
                        stage_root=private_root,
                        evaluator=evaluator,
                    )
                )
            except SeedAdmissionError as exc:
                rejected.append(
                    RejectedSeed(
                        index=index,
                        source_path=seed.source_path,
                        identity=candidate_id,
                        code=exc.code,
                    )
                )

    island_by_identity = {
        candidate_id: index % num_islands
        for index, candidate_id in enumerate(
            sorted(item.candidate_id for item in admitted_unassigned)
        )
    }
    admitted = tuple(
        AdmittedSeed(
            candidate_id=item.candidate_id,
            draft=item.draft,
            evaluation=item.evaluation,
            receipt=item.receipt,
            provenance=item.provenance,
            handoff_sha256=item.handoff_sha256,
            island_id=island_by_identity[item.candidate_id],
        )
        for item in admitted_unassigned
    )
    result = SeedAdmissionResult(admitted=admitted, rejected=tuple(rejected))
    if not admitted:
        raise SeedAdmissionError(NO_USABLE_SEEDS, result=result)
    return result


__all__ = [
    "CONTRACT_MISMATCH",
    "DEPENDENCY_MISMATCH",
    "DUPLICATE_IDENTITY",
    "DUPLICATE_SOURCE",
    "EMPTY_MANIFEST",
    "ENVIRONMENT_MISMATCH",
    "EVALUATOR_FAILED",
    "EVALUATOR_MISMATCH",
    "EVALUATOR_RECEIPT_SCHEMA_VERSION",
    "EXACT_HARNESS_KIND",
    "EXTERNAL_REQUIRES_EXACT_HARNESS",
    "EXTERNAL_SCORE_ONLY",
    "IDENTITY_COLLISION",
    "IDENTITY_MISMATCH",
    "INVALID_EVALUATION_REPORT",
    "LOCAL_EVALUATION_INVALID",
    "LOCAL_SCORE_UNAVAILABLE",
    "MANIFEST_INVALID",
    "MANIFEST_ROOT_REQUIRED",
    "MANIFEST_TOO_LARGE",
    "MAX_EXTERNAL_EVIDENCE_BYTES",
    "MAX_EXTERNAL_EVIDENCE_ITEMS",
    "MAX_LINEAGE_ITEMS",
    "MAX_MANIFEST_BYTES",
    "MAX_MATERIAL_REFS",
    "MAX_PATH_BYTES",
    "MAX_REFERENCE_BYTES",
    "MAX_SEEDS",
    "METADATA_TOO_LARGE",
    "MISSING_FIELD",
    "NO_USABLE_SEEDS",
    "RETAINED_ADMISSION_MISMATCH",
    "SEED_MANIFEST_SCHEMA_VERSION",
    "SOURCE_CHANGED",
    "SOURCE_DIGEST_MISMATCH",
    "SOURCE_EMPTY",
    "SOURCE_ENCODING_INVALID",
    "SOURCE_MISSING",
    "SOURCE_NOT_REGULAR",
    "SOURCE_TOO_LARGE",
    "SOURCE_UNSAFE",
    "STAGED_SOURCE_CHANGED",
    "TOO_MANY_SEEDS",
    "UNKNOWN_FIELD",
    "UNSUPPORTED_SCHEMA",
    "AdmittedSeed",
    "EvaluatorIdentity",
    "EvaluatorReceipt",
    "RejectedSeed",
    "SeedAdmissionError",
    "SeedAdmissionResult",
    "SeedIdentity",
    "SeedManifest",
    "SeedProvenance",
    "SeedRecord",
    "admit_seed_manifest",
    "compute_handoff_fingerprint",
    "compute_seed_identity",
    "parse_seed_manifest",
    "recover_retained_seed_admission",
    "seed_identity_material",
]
