"""Admit one OpenEvolve wrapper result through Lunar Evolution's verified seed boundary.

The wrapper protocol is intentionally smaller than OpenEvolve's internal data model.  It accepts
one confined candidate path plus optional, provenance-only evaluation evidence.  Candidate ranking
always comes from the injected local evaluator via :func:`admit_seed_manifest`.

The two generic identity slots required by the seed protocol have deliberately narrow meanings:

* ``source_only_dependency_sha256`` attests only to the bytes of the candidate source observed by
  this adapter.  It is not a digest of imports, datasets, or other transitive dependencies.
* ``declared_protocol_environment_sha256`` identifies this adapter's declared result protocol.  It
  is not a digest of the producer process, host, interpreter, packages, or material references.

Both identities are path-free and exclude producer provenance.  The caller-provided producer
fingerprint therefore cannot alter the stable ``seed-*`` candidate identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .algorithm import AlgorithmProblemContract, EvaluationReport
from .evolution import MAX_SOURCE_BYTES
from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
from .seed_handoff import AdmittedSeed, SeedManifest, admit_seed_manifest

OPENEVOLVE_RESULT_PROTOCOL = "lunar-openevolve-result-v1"
MAX_OPENEVOLVE_RESULT_BYTES = 64 * 1024
MAX_OPENEVOLVE_PATH_BYTES = 1_024
MAX_EXTERNAL_EVALUATION_NODES = 512
MAX_EXTERNAL_EVALUATION_DEPTH = 8
EXACT_HARNESS_KIND = "exact_harness"

EXTERNAL_ROOT_UNSAFE = "external_root_unsafe"
RESULT_PATH_UNSAFE = "result_path_unsafe"
RESULT_MISSING = "result_missing"
RESULT_NOT_REGULAR = "result_not_regular"
RESULT_TOO_LARGE = "result_too_large"
RESULT_ENCODING_INVALID = "result_encoding_invalid"
RESULT_JSON_INVALID = "result_json_invalid"
RESULT_SCHEMA_INVALID = "result_schema_invalid"
CANDIDATE_PATH_UNSAFE = "candidate_path_unsafe"
CANDIDATE_MISSING = "candidate_missing"
CANDIDATE_NOT_REGULAR = "candidate_not_regular"
CANDIDATE_TOO_LARGE = "candidate_too_large"
CANDIDATE_ENCODING_INVALID = "candidate_encoding_invalid"
EVALUATOR_FINGERPRINT_REQUIRED = "evaluator_fingerprint_required"
PRODUCER_FINGERPRINT_REQUIRED = "producer_fingerprint_required"
RESULT_BINDING_MISMATCH = "result_binding_mismatch"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token)\s*[:=]\s*\S+)"
)


class CandidateEvaluator(Protocol):
    def __call__(
        self,
        candidate_path: Path,
        contract: AlgorithmProblemContract,
    ) -> EvaluationReport | dict[str, Any]:
        """Return the authoritative local evaluation for a privately staged candidate."""


class OpenEvolveHandoffError(RuntimeError):
    """A fixed-code wrapper error that never includes paths or external prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DuplicateJsonKey(ValueError):
    pass


def _raise(code: str) -> None:
    raise OpenEvolveHandoffError(code)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        _raise(RESULT_SCHEMA_INVALID)


def _utf8_bytes(value: str, code: str) -> bytes:
    if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
        _raise(code)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        _raise(code)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _raise(code)
    return value


def _portable_relative_path(value: object, code: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _raise(code)
    if len(_utf8_bytes(value, code)) > MAX_OPENEVOLVE_PATH_BYTES or _CREDENTIAL_RE.search(value):
        _raise(code)
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _raise(code)
    return path.as_posix()


def _external_root(value: str | os.PathLike[str]) -> Path:
    try:
        raw = Path(value).expanduser()
        info = raw.lstat()
    except (OSError, TypeError, ValueError):
        _raise(EXTERNAL_ROOT_UNSAFE)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _raise(EXTERNAL_ROOT_UNSAFE)
    return Path(os.path.abspath(raw))


def _relative_to_root(
    root: Path,
    value: str | os.PathLike[str],
    *,
    code: str,
) -> str:
    try:
        raw = Path(value).expanduser()
    except (TypeError, ValueError):
        _raise(code)
    if raw.is_absolute():
        try:
            raw = Path(os.path.abspath(raw)).relative_to(root)
        except ValueError:
            _raise(code)
    return _portable_relative_path(raw.as_posix(), code)


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


def _read_confined_regular(
    root: Path,
    relative: str,
    *,
    limit: int,
    missing_code: str,
    regular_code: str,
    too_large_code: str,
    unsafe_code: str,
) -> bytes:
    """Read a stable regular-file snapshot without following path-component symlinks."""

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
            _raise(regular_code)
        if before.st_size > limit:
            _raise(too_large_code)

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
            _raise(too_large_code)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_size != len(content)
        ):
            _raise(unsafe_code)
        return content
    except OpenEvolveHandoffError:
        raise
    except FileNotFoundError:
        _raise(missing_code)
    except (NotADirectoryError, PermissionError):
        _raise(unsafe_code)
    except OSError:
        _raise(unsafe_code)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _parse_result(content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        _raise(RESULT_ENCODING_INVALID)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (json.JSONDecodeError, ValueError, _DuplicateJsonKey, RecursionError):
        _raise(RESULT_JSON_INVALID)
    if not isinstance(value, dict):
        _raise(RESULT_SCHEMA_INVALID)
    if set(value) - {"candidate_path", "evaluation"} or "candidate_path" not in value:
        _raise(RESULT_SCHEMA_INVALID)
    return value


def _validate_evaluation_tree(value: object) -> bool:
    """Bound untrusted evidence before canonical hashing; do not interpret its score."""

    if not isinstance(value, Mapping):
        _raise(RESULT_SCHEMA_INVALID)
    remaining: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    score_present = False
    while remaining:
        item, depth = remaining.pop()
        nodes += 1
        if nodes > MAX_EXTERNAL_EVALUATION_NODES or depth > MAX_EXTERNAL_EVALUATION_DEPTH:
            _raise(RESULT_SCHEMA_INVALID)
        if item is None or isinstance(item, bool):
            continue
        if isinstance(item, str):
            _utf8_bytes(item, RESULT_SCHEMA_INVALID)
            continue
        if isinstance(item, int):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                _raise(RESULT_SCHEMA_INVALID)
            continue
        if isinstance(item, list):
            remaining.extend((child, depth + 1) for child in item)
            continue
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    _raise(RESULT_SCHEMA_INVALID)
                _utf8_bytes(key, RESULT_SCHEMA_INVALID)
                normalized = key.casefold()
                if "score" in normalized or normalized in {"fitness", "quality", "reward"}:
                    score_present = True
                remaining.append((child, depth + 1))
            continue
        _raise(RESULT_SCHEMA_INVALID)
    return score_present


def source_only_dependency_sha256(source_sha256: str) -> str:
    """Identify only observed source bytes, without asserting dependency material verification."""

    source_sha256 = _require_digest(source_sha256, RESULT_SCHEMA_INVALID)
    return _sha256(
        {
            "schema_version": "1",
            "identity_kind": "source_only",
            "source_sha256": source_sha256,
            "verified_material_refs": [],
        }
    )


def declared_protocol_environment_sha256() -> str:
    """Identify the declared wrapper protocol, without claiming a runtime environment digest."""

    return _sha256(
        {
            "schema_version": "1",
            "identity_kind": "declared_protocol",
            "protocol": OPENEVOLVE_RESULT_PROTOCOL,
            "required_result_fields": ["candidate_path"],
            "optional_result_fields": ["evaluation"],
        }
    )


def admit_openevolve_result(
    external_root: str | os.PathLike[str],
    contract: AlgorithmProblemContract,
    evaluator: CandidateEvaluator,
    *,
    result_path: str | os.PathLike[str] = "result.json",
    evaluator_fingerprint: str,
    producer_fingerprint: str,
    producer_run_id: str | None = None,
    lineage: Sequence[str] = (),
    staging_root: str | os.PathLike[str] | None = None,
    num_islands: int = 1,
    binding: object | None = None,
) -> AdmittedSeed:
    """Convert one confined wrapper result to a locally evaluated Feature 084 seed.

    ``producer_fingerprint`` is provenance only.  Callers should pin it to the bounded producer
    command, budget, contract, and wrapper configuration they launched.  It is intentionally absent
    from both seed identity declarations.
    """

    evaluator_fingerprint = _require_digest(
        evaluator_fingerprint,
        EVALUATOR_FINGERPRINT_REQUIRED,
    )
    producer_fingerprint = _require_digest(
        producer_fingerprint,
        PRODUCER_FINGERPRINT_REQUIRED,
    )
    root = _external_root(external_root)
    relative_result = _relative_to_root(root, result_path, code=RESULT_PATH_UNSAFE)
    result_content = _read_confined_regular(
        root,
        relative_result,
        limit=MAX_OPENEVOLVE_RESULT_BYTES,
        missing_code=RESULT_MISSING,
        regular_code=RESULT_NOT_REGULAR,
        too_large_code=RESULT_TOO_LARGE,
        unsafe_code=RESULT_PATH_UNSAFE,
    )
    payload = _parse_result(result_content)
    candidate_path = _portable_relative_path(payload["candidate_path"], CANDIDATE_PATH_UNSAFE)
    source = _read_confined_regular(
        root,
        candidate_path,
        limit=MAX_SOURCE_BYTES,
        missing_code=CANDIDATE_MISSING,
        regular_code=CANDIDATE_NOT_REGULAR,
        too_large_code=CANDIDATE_TOO_LARGE,
        unsafe_code=CANDIDATE_PATH_UNSAFE,
    )
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        _raise(CANDIDATE_ENCODING_INVALID)

    raw_evaluation = payload.get("evaluation")
    evaluation_present = "evaluation" in payload
    evaluation_sha256: str | None = None
    external_score_present = False
    if evaluation_present:
        external_score_present = _validate_evaluation_tree(raw_evaluation)
        evaluation_sha256 = _sha256(raw_evaluation)

    if binding is not None:
        # This is an explicit composition gate only.  It binds the wrapper's
        # material/result metadata to the caller's immutable Python binding; it
        # never starts OpenEvolve or treats the wrapper score as authority.
        try:
            from .python_producer_adapter import verify_python_producer_result_binding

            envelope = ProducerResultEnvelope(
                schema_version="1",
                producer_id="openevolve",
                producer_fingerprint=producer_fingerprint,
                producer_run_id=getattr(binding, "run_id", None),
                status="completed",
                contract_sha256=contract.digest(),
                budget={"requests": 1},
                materials=(
                    ProducerMaterial(
                        kind="candidate_source",
                        path=candidate_path,
                        size=len(source),
                        sha256=hashlib.sha256(source).hexdigest(),
                        external_evidence={
                            "present": evaluation_present,
                            "score_present": external_score_present,
                            "payload_sha256": evaluation_sha256,
                        },
                    ),
                ),
            )
            verify_python_producer_result_binding(binding, envelope)
        except OpenEvolveHandoffError:
            raise
        except Exception as exc:
            raise OpenEvolveHandoffError(RESULT_BINDING_MISMATCH) from exc

    source_sha256 = hashlib.sha256(source).hexdigest()
    dependency_sha256 = source_only_dependency_sha256(source_sha256)
    environment_sha256 = declared_protocol_environment_sha256()
    manifest = SeedManifest.from_dict(
        {
            "schema_version": "1",
            "contract_sha256": contract.digest(),
            "evaluator": {
                "kind": EXACT_HARNESS_KIND,
                "fingerprint": evaluator_fingerprint,
            },
            "dependency_sha256": dependency_sha256,
            "environment_sha256": environment_sha256,
            "seeds": [
                {
                    "source_path": candidate_path,
                    "source_sha256": source_sha256,
                    "lineage": list(lineage),
                    "provenance": {
                        "origin_kind": "external",
                        "producer_id": "openevolve",
                        "producer_fingerprint": producer_fingerprint,
                        "producer_run_id": producer_run_id,
                        # No external material byte was verified by this adapter.
                        "material_refs": [],
                        "external_evidence": {
                            "present": evaluation_present,
                            "score_present": external_score_present,
                            "payload_sha256": evaluation_sha256,
                        },
                    },
                    "metadata": {
                        "adapter": "openevolve",
                        "external_evaluation_authority": "provenance_only",
                        "dependency_identity_kind": "source_only",
                        "environment_identity_kind": "declared_protocol",
                        "declared_protocol": OPENEVOLVE_RESULT_PROTOCOL,
                    },
                }
            ],
        },
        source_root=root,
    )
    result = admit_seed_manifest(
        manifest,
        contract,
        evaluator,
        evaluator_kind=EXACT_HARNESS_KIND,
        evaluator_fingerprint=evaluator_fingerprint,
        dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
        staging_root=staging_root,
        num_islands=num_islands,
    )
    return result.admitted[0]


__all__ = [
    "CANDIDATE_ENCODING_INVALID",
    "CANDIDATE_MISSING",
    "CANDIDATE_NOT_REGULAR",
    "CANDIDATE_PATH_UNSAFE",
    "CANDIDATE_TOO_LARGE",
    "EVALUATOR_FINGERPRINT_REQUIRED",
    "EXTERNAL_ROOT_UNSAFE",
    "MAX_OPENEVOLVE_RESULT_BYTES",
    "OPENEVOLVE_RESULT_PROTOCOL",
    "PRODUCER_FINGERPRINT_REQUIRED",
    "RESULT_BINDING_MISMATCH",
    "RESULT_ENCODING_INVALID",
    "RESULT_JSON_INVALID",
    "RESULT_MISSING",
    "RESULT_NOT_REGULAR",
    "RESULT_PATH_UNSAFE",
    "RESULT_SCHEMA_INVALID",
    "RESULT_TOO_LARGE",
    "OpenEvolveHandoffError",
    "admit_openevolve_result",
    "declared_protocol_environment_sha256",
    "source_only_dependency_sha256",
]
