"""Local, runtime-neutral evolution strategies.

The strategy layer deliberately knows nothing about Hermes, OpenCode, Codex, or a remote service.
It consumes an algorithm contract, an injected candidate generator, and an injected evaluator.  The
native population implementation maintains an append-only candidate archive; OpenEvolve is an
optional subprocess adapter rather than a package dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from .algorithm import (
    ACTIVE_EVOLUTION_STRATEGIES,
    ALGORITHM_FAMILY_REPERTOIRES,
    EVOLUTION_STRATEGIES,
    LOOP_STRATEGY_RETIRED_MESSAGE,
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILES,
    AlgorithmProblemContract,
    EvaluationReport,
    OutputSpec,
)
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .evaluator import evaluate_output_contract

MAX_SOURCE_BYTES = 512 * 1024
MAX_METADATA_BYTES = 8 * 1024
MAX_ARCHIVE_LINE_BYTES = 64 * 1024
MAX_STATE_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = MAX_STATE_BYTES * 128
MAX_EXTERNAL_RESULT_BYTES = 64 * 1024
MAX_ERROR_BYTES = 2_000
MAX_COMMAND_ARGS = 32
MAX_EXECUTION_OUTPUT_BYTES = 16 * 1024
MAX_EXECUTION_ERROR_BYTES = 512
MAX_EXECUTION_ARTIFACTS = 32
ORDINARY_CANDIDATE_RECEIPT_SCHEMA_VERSION = "1"
CANDIDATE_INTEGRITY_SCHEMA_VERSION = "1"
LEGACY_CANDIDATE_INTEGRITY_ERROR = "ordinary_candidate_integrity_required"
ORDINARY_RECEIPT_FILENAME = "receipt.json"
ORDINARY_RECORD_FILENAME = "record.json"
ORDINARY_EXECUTION_FILENAME = "execution.json"
_RESERVED_CANDIDATE_SOURCE_BASENAMES = frozenset(
    {
        ORDINARY_RECORD_FILENAME,
        ORDINARY_RECEIPT_FILENAME,
        ORDINARY_EXECUTION_FILENAME,
        f".{ORDINARY_RECORD_FILENAME}.tmp",
        f".{ORDINARY_RECEIPT_FILENAME}.tmp",
        f".{ORDINARY_EXECUTION_FILENAME}.tmp",
    }
)
_SEED_STAGE_NAME = ".evolution-seed-stage-v1"
_SEED_BACKUP_NAME = ".evolution-seed-backup-v1"
# Producer-bundle publication uses a separate transaction protocol.  Presence of this marker
# means that a batch may have crossed a filesystem commit boundary without a durable terminal
# result; ordinary archive readers and writers must fail closed until the transaction is resumed
# or explicitly adjudicated.
_PRODUCER_PUBLICATION_MARKER_NAME = "producer-publication.json"
_PRODUCER_PUBLICATION_RECOVERY_ERROR = "producer_bundle_publication_recovery_required"
# Process creation and interpreter startup can consume a few tens of milliseconds even for an
# empty candidate. A floor prevents a sub-scheduling-quantum budget from timing out before the
# candidate gets a chance to execute; longer budgets retain the requested value exactly.
MIN_PROCESS_TIMEOUT_SECONDS = 0.05
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_OUTPUT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)
_CREDENTIAL_METADATA_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth(?:orization)?|"
    r"password|passwd|secret|credential|bearer|private[_-]?key|token)(?:$|[_-])"
)
_OFFSPRING_OUTCOME_CODES = frozenset(
    {
        "evaluated",
        "candidate_failed",
        "evaluator_timeout",
        "worker_unknown",
        "run_failed",
    }
)
_MISSING_STRATEGY = object()
_WORKSPACE_STRATEGY_INVALID = "evolution_workspace_strategy_invalid"
_WORKSPACE_STRATEGY_MISMATCH = "evolution_workspace_strategy_mismatch"


class EvolutionError(RuntimeError):
    """A bounded, actionable strategy error."""


class WorkerUnknownError(EvolutionError):
    """Explicit signal that an evaluator worker's terminal state cannot be reconciled."""


class _InitialCandidateFailure(EvolutionError):
    """Fixed, non-prose outcome for a failed population initialization evaluation."""

    def __init__(self, code: str) -> None:
        if code not in _OFFSPRING_OUTCOME_CODES - {"evaluated"}:
            code = "run_failed"
        self.code = code
        super().__init__(code)


class _CandidateArchivePublicationUnknown(EvolutionError):
    """The archive append could not be durably confirmed or rolled back."""


def _bounded_error(error: object) -> str:
    text = " ".join(str(error).split())
    return text[-MAX_ERROR_BYTES:] if text else "unknown evolution error"


def _canonical_json_bytes(value: object) -> bytes:
    """Encode a bounded evidence value without permitting ambiguous JSON constants."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_json_loads(value: str | bytes) -> object:
    """Decode JSON while rejecting duplicate object keys and non-finite constants."""

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = item
        return result

    def reject_nonfinite(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    def parse_finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite JSON number")
        return result

    return json.loads(
        value,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite,
        parse_float=parse_finite_float,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _validate_bundle_attempt_ownership(
    candidates: Iterable[tuple[str, dict[str, Any] | None]],
) -> None:
    """One retained execution/evaluation can belong to only one ordinary candidate."""

    owners: dict[tuple[str, str], str] = {}
    for candidate_id, evidence in candidates:
        if evidence is None:
            continue
        from .bundle_evolution import validate_bundle_evidence_shape

        evidence = validate_bundle_evidence_shape(evidence)
        for name in ("run_root", "evaluation_path"):
            previous = owners.setdefault((name, evidence[name]), candidate_id)
            if previous != candidate_id:
                raise EvolutionError("bundle_candidate_execution_reused")


def _protocol_identity(label: str, payload: Mapping[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"protocol": label, "schema_version": "1"}
    if payload:
        body.update(payload)
    return _canonical_sha256(body)


def _native_dependency_identity() -> str:
    # This is a declared protocol identity, not a claim about transitive packages.  Callers that
    # can attest a stronger bundle may provide ``dependency_sha256`` explicitly.
    return _protocol_identity("lunar-native-candidate-dependencies-v1")


def _native_environment_identity() -> str:
    # Keep the fallback path-free and reproducible across machines running the same interpreter
    # family.  Host names, environment variables, and credentials never enter the digest.
    return _protocol_identity(
        "lunar-native-candidate-environment-v1",
        {
            "implementation": sys.implementation.name,
            "python": [sys.version_info.major, sys.version_info.minor, sys.version_info.micro],
            "platform": sys.platform,
        },
    )


def _native_evaluator_identity() -> str:
    return _protocol_identity("lunar-native-candidate-evaluator-v1")


def _native_generator_identity() -> str:
    return _protocol_identity("lunar-native-candidate-generator-v1")


def _native_runner_identity() -> str:
    return _protocol_identity("lunar-native-candidate-runner-none-v1")


def _normalize_receipt_error_codes(value: object) -> tuple[dict[str, str], ...]:
    """Project evaluator errors without retaining evaluator prose or secrets."""

    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise EvolutionError("ordinary_candidate_receipt_invalid")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"code", "message"}:
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        code = item.get("code")
        if not isinstance(code, str):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        normalized.append({"code": code, "message": "local evaluator reported an error"})
    return tuple(normalized)


def _sanitized_evaluation(report: EvaluationReport) -> EvaluationReport:
    """Return a report safe to persist in ordinary candidate evidence."""

    if not isinstance(report, EvaluationReport):
        raise EvolutionError("ordinary_candidate_receipt_invalid")
    try:
        errors = _normalize_receipt_error_codes(report.error_info)
        # Frozen dataclasses do not freeze nested dictionaries.  Take a canonical deep snapshot
        # so a callback cannot mutate its returned report after the evaluator boundary and change
        # receipt or archive bytes underneath an already computed digest.
        detailed_scores = json.loads(_canonical_json_bytes(report.detailed_scores).decode("utf-8"))
        return EvaluationReport(
            schema_version=report.schema_version,
            evaluator_id=report.evaluator_id,
            validity=report.validity,
            quality=report.quality,
            combined_score=report.combined_score,
            detailed_scores=detailed_scores,
            error_info=errors,
        )
    except (TypeError, ValueError, EvolutionError) as exc:
        raise EvolutionError("ordinary_candidate_receipt_invalid") from exc


def _sanitize_metadata(value: object, *, depth: int = 0) -> Any:
    """Normalize ordinary metadata before it crosses the durable archive boundary."""

    if depth > 8:
        raise EvolutionError("ordinary_candidate_metadata_invalid")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            value = _SECRET_OUTPUT.sub("[REDACTED]", value)
            if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise EvolutionError("ordinary_candidate_metadata_invalid")
            if len(value.encode("utf-8")) > 4_096:
                raise EvolutionError("ordinary_candidate_metadata_invalid")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvolutionError("ordinary_candidate_metadata_invalid")
        return float(value)
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise EvolutionError("ordinary_candidate_metadata_invalid")
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _SAFE_ID.fullmatch(key):
                raise EvolutionError("ordinary_candidate_metadata_invalid")
            if _SECRET_OUTPUT.search(key) or _CREDENTIAL_METADATA_KEY.search(key):
                # Keys cannot be redacted without risking collisions, so reject a credential-like
                # key before metadata reaches the record, archive, or controller event boundary.
                raise EvolutionError("ordinary_candidate_metadata_invalid")
            output[key] = _sanitize_metadata(item, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise EvolutionError("ordinary_candidate_metadata_invalid")
        return [_sanitize_metadata(item, depth=depth + 1) for item in value]
    raise EvolutionError("ordinary_candidate_metadata_invalid")


def _validate_ordinary_metadata(value: object) -> dict[str, Any]:
    """Return bounded ordinary metadata while reserving verified-seed identity markers."""

    normalized = _sanitize_metadata(value)
    if not isinstance(normalized, dict):
        raise EvolutionError("ordinary_candidate_metadata_invalid")
    if "seed_handoff" in normalized:
        raise EvolutionError("ordinary_candidate_seed_identity_reserved")
    return normalized


def _bounded_output(value: object, limit: int = MAX_EXECUTION_OUTPUT_BYTES) -> str:
    """Redact and cap process output before it crosses the execution evidence boundary."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value) if value is not None else ""
    text = _SECRET_OUTPUT.sub("[REDACTED]", text)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _safe_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise EvolutionError(f"{field_name} must be a safe identifier")
    return value


def _safe_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise EvolutionError(f"{field_name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvolutionError(f"{field_name} must be a relative path")
    return path.as_posix()


def _confined(root: Path, value: Path, field_name: str) -> Path:
    candidate = value.resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvolutionError(f"{field_name} escapes the run workspace") from exc
    return candidate


def _reject_symlink_components(path: Path, stop: Path, field_name: str) -> None:
    """Reject pre-existing symlink components before writing a confined artifact."""
    current = path
    stop = stop.resolve()
    while current != stop and current != current.parent:
        if current.is_symlink():
            raise EvolutionError(f"{field_name} must not contain a symlink")
        current = current.parent


def _read_bounded_regular_file(path: Path, limit: int, *, error: str) -> bytes:
    """Read at most ``limit`` bytes from one no-follow regular-file descriptor."""

    descriptor: int | None = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode) or information.st_size > limit:
            raise EvolutionError(error)
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > limit:
            raise EvolutionError(error)
        final_information = os.fstat(descriptor)
        if (
            not stat.S_ISREG(final_information.st_mode)
            or final_information.st_size > limit
            or final_information.st_size != len(content)
            or final_information.st_size != information.st_size
            or final_information.st_mtime_ns != information.st_mtime_ns
            or final_information.st_ctime_ns != information.st_ctime_ns
        ):
            raise EvolutionError(error)
        return content
    except EvolutionError:
        raise
    except OSError as exc:
        raise EvolutionError(error) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class _HeldRegularFileSnapshot:
    """One no-follow regular file held open across an untrusted callback boundary."""

    path: Path
    descriptor: int
    content: bytes
    information: os.stat_result
    limit: int
    error: str

    @classmethod
    def open(cls, path: Path, limit: int, *, error: str) -> _HeldRegularFileSnapshot:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > limit
            ):
                raise EvolutionError(error)
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            if len(content) > limit or not cls._same_snapshot(before, after, len(content)):
                raise EvolutionError(error)
            current = os.stat(path, follow_symlinks=False)
            if not cls._same_path_identity(after, current):
                raise EvolutionError(error)
            snapshot = cls(path, descriptor, content, after, limit, error)
            descriptor = None
            return snapshot
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError(error) from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    @staticmethod
    def _same_snapshot(
        before: os.stat_result,
        after: os.stat_result,
        content_size: int,
    ) -> bool:
        return (
            stat.S_ISREG(after.st_mode)
            and after.st_nlink == 1
            and after.st_size == content_size
            and after.st_size == before.st_size
            and after.st_dev == before.st_dev
            and after.st_ino == before.st_ino
            and after.st_mode == before.st_mode
            and after.st_mtime_ns == before.st_mtime_ns
            and after.st_ctime_ns == before.st_ctime_ns
        )

    @staticmethod
    def _same_path_identity(held: os.stat_result, current: os.stat_result) -> bool:
        return (
            stat.S_ISREG(current.st_mode)
            and current.st_nlink == 1
            and current.st_dev == held.st_dev
            and current.st_ino == held.st_ino
            and current.st_mode == held.st_mode
            and current.st_size == held.st_size
            and current.st_mtime_ns == held.st_mtime_ns
            and current.st_ctime_ns == held.st_ctime_ns
        )

    def validate(self, expected: bytes) -> None:
        """Reject content, metadata, inode, or path replacement during the held interval."""

        try:
            os.lseek(self.descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            remaining = self.limit + 1
            while remaining > 0:
                chunk = os.read(self.descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(self.descriptor)
            current = os.stat(self.path, follow_symlinks=False)
            if (
                len(content) > self.limit
                or content != self.content
                or content != expected
                or not self._same_snapshot(self.information, after, len(content))
                or not self._same_path_identity(after, current)
            ):
                raise EvolutionError(self.error)
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError(self.error) from exc

    def close(self) -> None:
        descriptor, self.descriptor = self.descriptor, -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _fsync_directory(path: Path, *, error: str) -> None:
    """Durably publish directory-entry changes without following the directory itself."""

    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise EvolutionError(error)
        os.fsync(descriptor)
    except EvolutionError:
        raise
    except OSError as exc:
        raise EvolutionError(error) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _fsync_directory_chain(start: Path, stop: Path, *, error: str) -> None:
    """Fsync a newly created directory chain from its leaf through ``stop``."""

    current = start
    stop = stop.resolve(strict=False)
    try:
        current.resolve(strict=False).relative_to(stop)
    except ValueError as exc:
        raise EvolutionError(error) from exc
    while True:
        _fsync_directory(current, error=error)
        if current.resolve(strict=False) == stop:
            return
        if current == current.parent:
            raise EvolutionError(error)
        current = current.parent


def _rollback_appended_regular_file(
    descriptor: int,
    root_descriptor: int,
    entry_name: str,
    previous_size: int,
) -> None:
    """Restore an append and confirm the directory entry still names the held inode."""

    def validate_identity() -> None:
        held = os.fstat(descriptor)
        current = os.stat(
            entry_name,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(held.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or held.st_nlink != 1
            or current.st_nlink != 1
            or held.st_size != previous_size
            or current.st_size != previous_size
            or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise OSError("append rollback identity changed")

    os.ftruncate(descriptor, previous_size)
    os.fsync(descriptor)
    validate_identity()
    os.fsync(root_descriptor)
    validate_identity()


@dataclass(frozen=True)
class CandidateInputArtifact:
    """One immutable, run-relative input admitted to candidate execution."""

    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        relative = _safe_relative_path(self.path, "candidate input path")
        if not relative.startswith("data/raw/") or relative == "data/raw/":
            raise ValueError("candidate input path must be below data/raw/")
        if len(relative.encode("utf-8")) > 1_024:
            raise ValueError("candidate input path exceeds the bounded path limit")
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_INPUT_FILE_BYTES
        ):
            raise ValueError("candidate input size is invalid")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("candidate input sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "path", relative)


def stage_candidate_inputs(
    source_workspace: Path,
    destination_workspace: Path,
    inputs: Sequence[CandidateInputArtifact],
) -> tuple[str, ...]:
    """Digest-check and atomically copy immutable inputs between private workspaces."""
    raw_source_root = Path(source_workspace).expanduser()
    raw_destination_root = Path(destination_workspace).expanduser()
    if raw_source_root.is_symlink() or raw_destination_root.is_symlink():
        raise EvolutionError("candidate input workspace must not be a symlink")
    source_root = raw_source_root.resolve(strict=False)
    destination_root = raw_destination_root.resolve(strict=False)
    if not source_root.is_dir():
        raise EvolutionError("candidate input source workspace is missing")
    destination_root.mkdir(parents=True, exist_ok=True)
    if len(inputs) > MAX_INPUT_FILES:
        raise EvolutionError("candidate input list exceeds the bounded file limit")

    copied: list[str] = []
    for descriptor in inputs:
        if not isinstance(descriptor, CandidateInputArtifact):
            raise TypeError("candidate inputs must contain CandidateInputArtifact records")
        raw_source = source_root / descriptor.path
        _reject_symlink_components(raw_source, source_root, "candidate input source path")
        source = _confined(source_root, raw_source, "candidate input source path")
        if raw_source.is_symlink() or not source.is_file():
            raise EvolutionError(f"candidate input source is missing or unsafe: {descriptor.path}")
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != descriptor.size or digest != descriptor.sha256:
            raise EvolutionError(f"candidate input digest does not match: {descriptor.path}")

        raw_target = destination_root / descriptor.path
        _reject_symlink_components(raw_target, destination_root, "candidate input target path")
        target = _confined(destination_root, raw_target, "candidate input target path")
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(raw_target, destination_root, "candidate input target path")
        if raw_target.is_symlink():
            raise EvolutionError(f"candidate input target is unsafe: {descriptor.path}")
        if target.exists():
            if not target.is_file():
                raise EvolutionError(f"candidate input target is unsafe: {descriptor.path}")
            existing = target.read_bytes()
            if len(existing) != descriptor.size or hashlib.sha256(existing).hexdigest() != digest:
                raise EvolutionError(
                    f"candidate input target already contains different data: {descriptor.path}"
                )
        else:
            temporary = target.with_name(f".{target.name}.input.tmp")
            if temporary.is_symlink():
                raise EvolutionError(f"candidate input temporary path is unsafe: {descriptor.path}")
            if temporary.exists():
                stale = temporary.read_bytes() if temporary.is_file() else b""
                if len(stale) != descriptor.size or hashlib.sha256(stale).hexdigest() != digest:
                    raise EvolutionError(
                        f"candidate input temporary path contains different data: {descriptor.path}"
                    )
            else:
                with temporary.open("xb") as stream:
                    stream.write(content)
            try:
                os.link(temporary, target)
            except FileExistsError:
                concurrent = target.read_bytes() if target.is_file() else b""
                if (
                    len(concurrent) != descriptor.size
                    or hashlib.sha256(concurrent).hexdigest() != digest
                ):
                    raise EvolutionError(
                        f"candidate input target already contains different data: {descriptor.path}"
                    )
            else:
                temporary.unlink()
        if target.stat().st_size != descriptor.size or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise EvolutionError(f"candidate input copy digest does not match: {descriptor.path}")
        copied.append(descriptor.path)
    return tuple(copied)


def contract_candidate_runner_fingerprint(
    contract: AlgorithmProblemContract,
    inputs: Sequence[CandidateInputArtifact],
) -> str:
    """Return a path- and credential-free identity for the built-in search protocol."""
    if not isinstance(contract, AlgorithmProblemContract):
        raise TypeError("contract must be an AlgorithmProblemContract")
    normalized = tuple(inputs)
    if len(normalized) > MAX_INPUT_FILES:
        raise ValueError("candidate input list exceeds the bounded file limit")
    if any(not isinstance(item, CandidateInputArtifact) for item in normalized):
        raise TypeError("inputs must contain CandidateInputArtifact records")
    if len({item.path for item in normalized}) != len(normalized):
        raise ValueError("candidate input paths must be unique")
    payload = {
        "protocol": "contract-candidate-runner-v1",
        "python": {
            "implementation": sys.implementation.name,
            "version": [sys.version_info.major, sys.version_info.minor, sys.version_info.micro],
        },
        "contract_sha256": contract.digest(),
        "inputs": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in sorted(normalized, key=lambda item: item.path)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateDraft:
    """Unpersisted source returned by a candidate generator."""

    source: str
    filename: str = "candidate.py"
    metadata: dict[str, Any] = field(default_factory=dict)
    # When present this is the complete source tree, including ``filename`` and its exact source.
    source_files: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise EvolutionError("candidate source must be non-empty text")
        if len(self.source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise EvolutionError("candidate source exceeds the bounded source limit")
        _safe_relative_path(self.filename, "candidate filename")
        encoded = json.dumps(self.metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise EvolutionError("candidate metadata exceeds the bounded metadata limit")
        if self.source_files is not None:
            from .bundle_evolution import validate_bundle_draft

            validate_bundle_draft(self, "0" * 64)
            object.__setattr__(self, "source_files", dict(self.source_files))

    @classmethod
    def from_files(
        cls,
        files: dict[str, str],
        entrypoint: str,
        metadata: dict[str, Any] | None = None,
    ) -> CandidateDraft:
        if not isinstance(files, dict) or not isinstance(entrypoint, str) or entrypoint not in files:
            raise EvolutionError("bundle_candidate_draft_invalid")
        return cls(files[entrypoint], entrypoint, {} if metadata is None else metadata, files)


@dataclass(frozen=True)
class CandidateExecution:
    """Bounded evidence from one candidate process invocation."""

    status: Literal["succeeded", "failed", "timed_out"]
    exit_code: int | None
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "timed_out"}:
            raise ValueError("execution status must be succeeded, failed, or timed_out")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("execution exit_code must be an integer or null")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or self.duration_ms < 0
            or self.duration_ms > 86_400_000
        ):
            raise ValueError("execution duration_ms must be a bounded non-negative integer")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise TypeError("execution stdout and stderr must be text")
        normalized_stdout = _bounded_output(self.stdout)
        normalized_stderr = _bounded_output(self.stderr)
        object.__setattr__(self, "stdout", normalized_stdout)
        object.__setattr__(self, "stderr", normalized_stderr)
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("execution error must be text or null")
        if self.error is not None:
            object.__setattr__(self, "error", _bounded_output(self.error, MAX_EXECUTION_ERROR_BYTES).strip())
        for name, value in (("stdout", normalized_stdout), ("stderr", normalized_stderr)):
            if len(value.encode("utf-8")) > MAX_EXECUTION_OUTPUT_BYTES:
                raise ValueError(f"execution {name} exceeds the bounded output limit")
        if self.error is not None and len(self.error.encode("utf-8")) > MAX_EXECUTION_ERROR_BYTES:
            raise ValueError("execution error must be bounded text")
        if len(self.artifacts) > MAX_EXECUTION_ARTIFACTS:
            raise ValueError("execution has too many artifacts")
        if len(set(self.artifacts)) != len(self.artifacts):
            raise ValueError("execution artifact paths must be unique")
        for relative in self.artifacts:
            _safe_relative_path(relative, "execution artifact path")

    @property
    def stdout_bytes(self) -> int:
        return len(self.stdout.encode("utf-8"))

    @property
    def stderr_bytes(self) -> int:
        return len(self.stderr.encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "artifacts": list(self.artifacts),
        }

    @classmethod
    def from_dict(cls, value: object) -> CandidateExecution:
        if not isinstance(value, dict):
            raise TypeError("candidate execution must be an object")
        artifacts = value.get("artifacts", [])
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise TypeError("execution artifacts must be a string array")
        return cls(
            status=value.get("status"),  # type: ignore[arg-type]
            exit_code=value.get("exit_code"),  # type: ignore[arg-type]
            duration_ms=value.get("duration_ms"),  # type: ignore[arg-type]
            stdout=value.get("stdout", ""),  # type: ignore[arg-type]
            stderr=value.get("stderr", ""),  # type: ignore[arg-type]
            error=value.get("error"),  # type: ignore[arg-type]
            artifacts=tuple(artifacts),
        )


class CandidateRunner(Protocol):
    """Execute a candidate in a bounded, run-scoped workspace."""

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        ...


def _write_execution_evidence(workspace: Path, execution: CandidateExecution) -> Path:
    raw_workspace = Path(workspace).expanduser()
    if raw_workspace.is_symlink():
        raise EvolutionError("candidate execution workspace must not be a symlink")
    workspace = raw_workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    evidence = workspace / "execution.json"
    if evidence.is_symlink() or (evidence.exists() and not evidence.is_file()):
        raise EvolutionError("candidate execution evidence must not be a symlink")
    temporary = workspace / ".execution.json.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise EvolutionError("candidate execution temporary evidence must not be a symlink")
    content = (
        json.dumps(execution.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        # The runner creates this node only after the candidate process has returned. Publish the
        # directory entry first so even a later partial write is durable execution evidence and
        # must block a replay.
        _fsync_directory(
            workspace,
            error="candidate execution evidence could not be persisted",
        )
        view = memoryview(content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("candidate execution evidence write made no progress")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, evidence)
        _fsync_directory(
            workspace,
            error="candidate execution evidence could not be persisted",
        )
    except OSError as exc:
        raise EvolutionError("candidate execution evidence could not be persisted") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    return evidence


def _collect_declared_artifacts(workspace: Path) -> tuple[str, ...]:
    """Validate the optional execution-artifacts.json manifest emitted by a runner."""
    manifest = workspace / "execution-artifacts.json"
    if not manifest.exists():
        return ()
    if manifest.is_symlink():
        raise EvolutionError("candidate execution artifact manifest must not be a symlink")
    if manifest.stat().st_size > MAX_EXECUTION_OUTPUT_BYTES:
        raise EvolutionError("candidate execution artifact manifest exceeds the bounded size")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvolutionError("candidate execution artifact manifest is invalid") from exc
    if not isinstance(payload, list) or len(payload) > MAX_EXECUTION_ARTIFACTS:
        raise EvolutionError("candidate execution artifact manifest must be a bounded array")
    output: list[str] = []
    for value in payload:
        relative = _safe_relative_path(value, "execution artifact path")
        if relative in output:
            raise EvolutionError("execution artifact paths must be unique")
        path = (workspace / relative).resolve(strict=False)
        _confined(workspace, path, "execution artifact path")
        if (workspace / relative).is_symlink() or not path.is_file():
            raise EvolutionError("execution artifact must be a regular file")
        output.append(relative)
    return tuple(output)


def _kill_candidate_process_group(process: subprocess.Popen[str]) -> bool:
    """Best-effort terminal cleanup for the private session created by a candidate run."""

    kill_group = getattr(os, "killpg", None)
    if callable(kill_group):
        try:
            # ``start_new_session=True`` makes the child's PID the stable process-group ID. Using
            # it directly still reaches descendants after the original process has already exited.
            kill_group(process.pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            return False
    if process.poll() is not None:
        # Without a process-group primitive an exited parent leaves descendant cleanup uncertain.
        return False
    try:
        process.kill()
        return True
    except (OSError, ProcessLookupError):
        return process.poll() is not None


class CommandCandidateRunner:
    """Run a candidate through an explicit local command without a shell."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float = 900.0,
        max_output_bytes: int = MAX_EXECUTION_OUTPUT_BYTES,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("candidate runner command must be a non-empty bounded argument sequence")
        executable = Path(command[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("candidate runner command must start with an existing absolute executable path")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("candidate runner timeout must be positive")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 1 <= max_output_bytes <= MAX_EXECUTION_OUTPUT_BYTES
        ):
            raise ValueError("candidate runner output limit is invalid")
        self.command = command
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = max_output_bytes
        if environment is None:
            self.environment = None
        else:
            if len(environment) > 64:
                raise ValueError("candidate runner environment has too many entries")
            normalized_environment: dict[str, str] = {}
            for key, value in environment.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or "\x00" in key
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    raise ValueError("candidate runner environment is invalid")
                if len(key.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 4_096:
                    raise ValueError("candidate runner environment entry is too large")
                normalized_environment[key] = value
            self.environment = normalized_environment

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink():
            raise EvolutionError("candidate runner workspace must not be a symlink")
        workspace = raw_workspace.resolve(strict=False)
        raw_candidate = Path(candidate_path).expanduser()
        if raw_candidate.is_symlink():
            raise EvolutionError("candidate runner path must not be a symlink")
        candidate = raw_candidate.resolve(strict=False)
        if not candidate.is_file():
            raise EvolutionError("candidate runner received a missing candidate path")
        _confined(workspace, candidate, "candidate runner path")
        effective_timeout = self.timeout_seconds if timeout is None else timeout
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or not math.isfinite(float(effective_timeout))
            or effective_timeout <= 0
        ):
            raise ValueError("candidate runner timeout must be positive")
        effective_timeout = (
            max(float(effective_timeout), MIN_PROCESS_TIMEOUT_SECONDS)
            if timeout is None else min(self.timeout_seconds, float(effective_timeout))
        )
        workspace.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        error: str | None = None
        status: Literal["succeeded", "failed", "timed_out"] = "failed"
        exit_code: int | None = None
        try:
            process = subprocess.Popen(
                [*self.command, str(candidate)],
                cwd=workspace,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            stdout, stderr = process.communicate(timeout=float(effective_timeout))
            exit_code = process.returncode
            cleanup_confirmed = _kill_candidate_process_group(process)
            output_overflow = (
                len(str(stdout).encode("utf-8")) > self.max_output_bytes
                or len(str(stderr).encode("utf-8")) > self.max_output_bytes
            )
            stdout = _bounded_output(stdout, self.max_output_bytes).strip()
            stderr = _bounded_output(stderr, self.max_output_bytes).strip()
            if output_overflow:
                error = "output_limit_exceeded"
            elif not cleanup_confirmed:
                error = "candidate_process_cleanup_failed"
            elif exit_code == 0:
                status = "succeeded"
            else:
                error = "candidate_process_failed"
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                _kill_candidate_process_group(process)
                raw_stdout, raw_stderr = process.communicate()
                stdout = _bounded_output(raw_stdout, self.max_output_bytes).strip()
                stderr = _bounded_output(raw_stderr, self.max_output_bytes).strip()
            else:
                stdout = _bounded_output(exc.stdout, self.max_output_bytes).strip()
                stderr = _bounded_output(exc.stderr, self.max_output_bytes).strip()
            error = "candidate_process_timed_out"
            status = "timed_out"
        except OSError as exc:
            error = "runner_start_failed"
            stderr = _bounded_output(str(exc), self.max_output_bytes).strip()
        artifacts: tuple[str, ...] = ()
        try:
            artifacts = _collect_declared_artifacts(workspace)
        except EvolutionError as exc:
            status = "failed"
            error = "artifact_manifest_invalid"
            stderr = _bounded_output(str(exc), self.max_output_bytes).strip()
        duration_ms = min(86_400_000, max(0, round((time.monotonic() - started) * 1000)))
        execution = CandidateExecution(
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            error=error,
            artifacts=artifacts,
        )
        _write_execution_evidence(workspace, execution)
        return execution


class ContractCandidateRunner:
    """Run Python candidates against copied inputs and an immutable output contract."""

    def __init__(
        self,
        source_workspace: Path,
        inputs: Sequence[CandidateInputArtifact],
        outputs: Sequence[OutputSpec],
        timeout_seconds: float = 900.0,
    ) -> None:
        raw_source = Path(source_workspace).expanduser()
        if raw_source.is_symlink():
            raise EvolutionError("candidate input source workspace must not be a symlink")
        normalized_inputs = tuple(inputs)
        normalized_outputs = tuple(outputs)
        if len(normalized_inputs) > MAX_INPUT_FILES:
            raise ValueError("candidate input list exceeds the bounded file limit")
        if any(not isinstance(item, CandidateInputArtifact) for item in normalized_inputs):
            raise TypeError("inputs must contain CandidateInputArtifact records")
        if len({item.path for item in normalized_inputs}) != len(normalized_inputs):
            raise ValueError("candidate input paths must be unique")
        if len(normalized_outputs) > MAX_EXECUTION_ARTIFACTS:
            raise ValueError("candidate output list exceeds the bounded file limit")
        if any(not isinstance(item, OutputSpec) for item in normalized_outputs):
            raise TypeError("outputs must contain OutputSpec records")
        if len({item.path for item in normalized_outputs}) != len(normalized_outputs):
            raise ValueError("candidate output paths must be unique")
        self.source_workspace = raw_source.resolve(strict=False)
        self.inputs = normalized_inputs
        self.outputs = normalized_outputs
        self.timeout_seconds = timeout_seconds
        self.process_runner = CommandCandidateRunner(
            (sys.executable, "-I"),
            timeout_seconds=timeout_seconds,
            environment={
                "PYTHONHASHSEED": "0",
                "PYTHONIOENCODING": "utf-8",
            },
        )

    def stage_inputs(self, destination_workspace: Path) -> tuple[str, ...]:
        """Expose the same verified copy boundary to Agent generation workspaces."""
        return stage_candidate_inputs(
            self.source_workspace,
            destination_workspace,
            self.inputs,
        )

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        raw_candidate = Path(candidate_path).expanduser()
        if raw_candidate.suffix.lower() != ".py":
            raise EvolutionError("contract candidate runner requires a .py candidate")
        self.stage_inputs(workspace)
        execution = self.process_runner.run(raw_candidate, workspace, timeout)
        if execution.status != "succeeded":
            normalized = CandidateExecution(
                status=execution.status,
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                stdout=execution.stdout,
                stderr=execution.stderr,
                error=execution.error,
                artifacts=(),
            )
            _write_execution_evidence(workspace, normalized)
            return normalized

        validation = evaluate_output_contract(self.outputs, Path(workspace))
        if not validation.passed:
            stderr = "\n".join(
                value for value in (execution.stderr, validation.reason) if value
            )
            failed = CandidateExecution(
                status="failed",
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                stdout=execution.stdout,
                stderr=_bounded_output(stderr, MAX_EXECUTION_OUTPUT_BYTES),
                error="output_contract_invalid",
                artifacts=(),
            )
            _write_execution_evidence(workspace, failed)
            return failed

        artifacts = tuple(
            output.path
            for output in self.outputs
            if (Path(workspace) / output.path).is_file()
            and not (Path(workspace) / output.path).is_symlink()
        )
        succeeded = CandidateExecution(
            status="succeeded",
            exit_code=execution.exit_code,
            duration_ms=execution.duration_ms,
            stdout=execution.stdout,
            stderr=execution.stderr,
            artifacts=artifacts,
        )
        _write_execution_evidence(workspace, succeeded)
        return succeeded


@dataclass(frozen=True)
class EvolutionConfig:
    """Explicit, bounded knobs shared by all strategies."""

    strategy: Literal["population", "openevolve"] = "population"
    max_rounds: int = 5
    stagnation_rounds: int = 3
    population_size: int = 8
    offspring_per_iteration: int = 1
    num_islands: int = 1
    migration_interval: int = 0
    migration_rate: float = 0.1
    rng_seed: int | None = None
    timeout_seconds: float = 900.0
    command: tuple[str, ...] = ()
    generator_fingerprint: str | None = None
    evaluator_fingerprint: str | None = None
    runner_fingerprint: str | None = None
    evaluator_kind: str | None = None
    dependency_sha256: str | None = None
    environment_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.strategy == "loop":
            raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if self.strategy not in ACTIVE_EVOLUTION_STRATEGIES:
            raise ValueError("strategy must be population or openevolve")
        for name, value, maximum in (
            ("max_rounds", self.max_rounds, 10_000),
            ("stagnation_rounds", self.stagnation_rounds, 1_000),
            ("population_size", self.population_size, 10_000),
            ("offspring_per_iteration", self.offspring_per_iteration, 256),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be a positive bounded integer")
        if isinstance(self.num_islands, bool) or not isinstance(self.num_islands, int):
            raise TypeError("num_islands must be a positive bounded integer")
        if not 1 <= self.num_islands <= 64 or self.num_islands > self.population_size:
            raise ValueError("num_islands must be between 1 and population_size")
        if isinstance(self.migration_interval, bool) or not isinstance(self.migration_interval, int):
            raise TypeError("migration_interval must be a non-negative integer")
        if not 0 <= self.migration_interval <= 10_000:
            raise ValueError("migration_interval must be a non-negative bounded integer")
        if isinstance(self.migration_rate, bool) or not isinstance(self.migration_rate, (int, float)):
            raise TypeError("migration_rate must be a number between 0 and 1")
        if not math.isfinite(float(self.migration_rate)) or not 0 <= self.migration_rate <= 1:
            raise ValueError("migration_rate must be a number between 0 and 1")
        if self.rng_seed is not None and (isinstance(self.rng_seed, bool) or not isinstance(self.rng_seed, int)):
            raise ValueError("rng_seed must be an integer or null")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be positive")
        if not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(self.command, tuple) or len(self.command) > MAX_COMMAND_ARGS:
            raise ValueError("command must be a bounded argument tuple")
        if any(not isinstance(arg, str) or not arg for arg in self.command):
            raise ValueError("command arguments must be non-empty strings")
        for name, fingerprint in (
            ("generator_fingerprint", self.generator_fingerprint),
            ("evaluator_fingerprint", self.evaluator_fingerprint),
            ("runner_fingerprint", self.runner_fingerprint),
            ("dependency_sha256", self.dependency_sha256),
            ("environment_sha256", self.environment_sha256),
        ):
            if fingerprint is not None and (
                not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest or null")
        if self.evaluator_kind is not None and (
            not isinstance(self.evaluator_kind, str)
            or not _SAFE_ID.fullmatch(self.evaluator_kind)
            or _SECRET_OUTPUT.search(self.evaluator_kind)
        ):
            raise ValueError("evaluator_kind must be a safe identifier or null")
        if self.strategy == "openevolve":
            if not self.command:
                raise ValueError("openevolve strategy requires an explicit command")
            if self.evaluator_fingerprint is None:
                raise ValueError("openevolve strategy requires a pinned local evaluator fingerprint")

    def to_dict(self) -> dict[str, Any]:
        """Return a credential-safe configuration snapshot for resume validation."""
        command_digest = None
        if self.command:
            command_digest = hashlib.sha256(
                json.dumps(list(self.command), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        payload = {
            "strategy": self.strategy,
            "max_rounds": self.max_rounds,
            "stagnation_rounds": self.stagnation_rounds,
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "migration_interval": self.migration_interval,
            "migration_rate": self.migration_rate,
            "rng_seed": self.rng_seed,
            "timeout_seconds": self.timeout_seconds,
            "command_sha256": command_digest,
        }
        if self.generator_fingerprint is not None:
            payload["generator_fingerprint"] = self.generator_fingerprint
        if self.evaluator_fingerprint is not None:
            payload["evaluator_fingerprint"] = self.evaluator_fingerprint
        if self.runner_fingerprint is not None:
            payload["runner_fingerprint"] = self.runner_fingerprint
        if self.evaluator_kind is not None:
            payload["evaluator_kind"] = self.evaluator_kind
        if self.dependency_sha256 is not None:
            payload["dependency_sha256"] = self.dependency_sha256
        if self.environment_sha256 is not None:
            payload["environment_sha256"] = self.environment_sha256
        return payload


@dataclass(frozen=True)
class PopulationConfig:
    """Bounded native population settings."""

    population_size: int = 8
    offspring_per_iteration: int = 1
    num_islands: int = 1
    migration_interval: int = 0
    migration_rate: float = 0.1
    rng_seed: int | None = None

    def __post_init__(self) -> None:
        # Reuse the canonical bounds and type checks without duplicating policy in two models.
        EvolutionConfig(
            strategy="population",
            population_size=self.population_size,
            offspring_per_iteration=self.offspring_per_iteration,
            num_islands=self.num_islands,
            migration_interval=self.migration_interval,
            migration_rate=self.migration_rate,
            rng_seed=self.rng_seed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "migration_interval": self.migration_interval,
            "migration_rate": self.migration_rate,
            "rng_seed": self.rng_seed,
        }


@dataclass(frozen=True)
class CandidateReceipt:
    """Canonical, evaluator-bound receipt for an ordinary candidate.

    Version 1 retains the single-file receipt shape. Version 2 additionally binds the complete
    source bundle and retained independent evaluation. The local lineage and runner identities
    remain shared with ordinary population candidates.
    """

    schema_version: str
    candidate_id: str
    source_sha256: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    runner_fingerprint: str
    generator_fingerprint: str
    parent_id: str | None
    generation: int
    iteration: int
    island_id: int | None
    report_schema_version: str
    evaluator_id: str
    validity: int
    quality: float | None
    combined_score: float
    detailed_scores: dict[str, dict[str, Any]]
    error_info: tuple[dict[str, str], ...]
    receipt_sha256: str
    execution_sha256: str | None = None
    bundle_evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.schema_version not in (ORDINARY_CANDIDATE_RECEIPT_SCHEMA_VERSION, "2"):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        if (self.schema_version == "2") != (self.bundle_evidence is not None):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        if self.bundle_evidence is not None:
            from .bundle_evolution import validate_bundle_evidence_shape

            object.__setattr__(self, "bundle_evidence", validate_bundle_evidence_shape(self.bundle_evidence))
        _safe_id(self.candidate_id, "candidate receipt candidate_id")
        for name in (
            "source_sha256",
            "contract_sha256",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "runner_fingerprint",
            "generator_fingerprint",
            "receipt_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise EvolutionError("ordinary_candidate_receipt_invalid")
        _safe_id(self.evaluator_kind, "candidate receipt evaluator_kind")
        if _SECRET_OUTPUT.search(self.evaluator_kind):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        if self.parent_id is not None:
            _safe_id(self.parent_id, "candidate receipt parent_id")
        for name in ("generation", "iteration"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvolutionError("ordinary_candidate_receipt_invalid")
        if self.island_id is not None and (
            isinstance(self.island_id, bool)
            or not isinstance(self.island_id, int)
            or self.island_id < 0
        ):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        if self.report_schema_version != "1":
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        if self.execution_sha256 is not None and (
            not isinstance(self.execution_sha256, str)
            or not _SHA256.fullmatch(self.execution_sha256)
        ):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        try:
            report = EvaluationReport(
                schema_version=self.report_schema_version,
                evaluator_id=self.evaluator_id,
                validity=self.validity,
                quality=self.quality,
                combined_score=self.combined_score,
                detailed_scores=self.detailed_scores,
                error_info=self.error_info,
            )
        except (TypeError, ValueError, EvolutionError) as exc:
            raise EvolutionError("ordinary_candidate_receipt_invalid") from exc
        normalized = _sanitized_evaluation(report)
        if tuple(self.error_info) != normalized.error_info:
            # ``from_report`` canonicalizes messages before constructing the receipt.  Parsed
            # receipts must already contain that canonical projection; otherwise changing prose
            # could be hidden by normalization before the receipt digest is checked.
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        object.__setattr__(self, "quality", normalized.quality)
        object.__setattr__(self, "combined_score", normalized.combined_score)
        object.__setattr__(self, "detailed_scores", normalized.detailed_scores)
        object.__setattr__(self, "error_info", tuple(normalized.error_info))
        if self.receipt_sha256 != _canonical_sha256(self.canonical_payload()):
            raise EvolutionError("ordinary_candidate_receipt_invalid")

    def canonical_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "source_sha256": self.source_sha256,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "runner_fingerprint": self.runner_fingerprint,
            "generator_fingerprint": self.generator_fingerprint,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "island_id": self.island_id,
            "report_schema_version": self.report_schema_version,
            "evaluator_id": self.evaluator_id,
            "validity": self.validity,
            "quality": self.quality,
            "combined_score": self.combined_score,
            "detailed_scores": self.detailed_scores,
            "error_info": list(self.error_info),
            "execution_sha256": self.execution_sha256,
        }
        if self.schema_version == "2":
            payload["bundle_evidence"] = self.bundle_evidence
        return payload

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
        runner_fingerprint: str,
        generator_fingerprint: str,
        parent_id: str | None,
        generation: int,
        iteration: int,
        island_id: int | None,
        execution_sha256: str | None = None,
        bundle_evidence: dict[str, Any] | None = None,
    ) -> CandidateReceipt:
        normalized = _sanitized_evaluation(report)
        payload = {
            "schema_version": "2" if bundle_evidence is not None else ORDINARY_CANDIDATE_RECEIPT_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "source_sha256": source_sha256,
            "contract_sha256": contract_sha256,
            "evaluator_kind": evaluator_kind,
            "evaluator_fingerprint": evaluator_fingerprint,
            "dependency_sha256": dependency_sha256,
            "environment_sha256": environment_sha256,
            "runner_fingerprint": runner_fingerprint,
            "generator_fingerprint": generator_fingerprint,
            "parent_id": parent_id,
            "generation": generation,
            "iteration": iteration,
            "island_id": island_id,
            "report_schema_version": normalized.schema_version,
            "evaluator_id": normalized.evaluator_id,
            "validity": normalized.validity,
            "quality": normalized.quality,
            "combined_score": normalized.combined_score,
            "detailed_scores": normalized.detailed_scores,
            "error_info": list(normalized.error_info),
            "execution_sha256": execution_sha256,
        }
        if bundle_evidence is not None:
            from .bundle_evolution import validate_bundle_evidence_shape

            payload["bundle_evidence"] = validate_bundle_evidence_shape(bundle_evidence)
        return cls(**payload, receipt_sha256=_canonical_sha256(payload))

    @classmethod
    def from_dict(cls, value: object) -> CandidateReceipt:
        if not isinstance(value, dict):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        required = {
            "schema_version",
            "candidate_id",
            "source_sha256",
            "contract_sha256",
            "evaluator_kind",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "runner_fingerprint",
            "generator_fingerprint",
            "parent_id",
            "generation",
            "iteration",
            "island_id",
            "report_schema_version",
            "evaluator_id",
            "validity",
            "quality",
            "combined_score",
            "detailed_scores",
            "error_info",
            "receipt_sha256",
            "execution_sha256",
        }
        if value.get("schema_version") == "2":
            required.add("bundle_evidence")
        if set(value) != required:
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        errors = value["error_info"]
        if not isinstance(errors, list):
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        return cls(
            schema_version=value["schema_version"],
            candidate_id=value["candidate_id"],
            source_sha256=value["source_sha256"],
            contract_sha256=value["contract_sha256"],
            evaluator_kind=value["evaluator_kind"],
            evaluator_fingerprint=value["evaluator_fingerprint"],
            dependency_sha256=value["dependency_sha256"],
            environment_sha256=value["environment_sha256"],
            runner_fingerprint=value["runner_fingerprint"],
            generator_fingerprint=value["generator_fingerprint"],
            parent_id=value["parent_id"],
            generation=value["generation"],
            iteration=value["iteration"],
            island_id=value["island_id"],
            report_schema_version=value["report_schema_version"],
            evaluator_id=value["evaluator_id"],
            validity=value["validity"],
            quality=value["quality"],
            combined_score=value["combined_score"],
            detailed_scores=value["detailed_scores"],
            error_info=tuple(errors),
            receipt_sha256=value["receipt_sha256"],
            execution_sha256=value["execution_sha256"],
            bundle_evidence=value.get("bundle_evidence"),
        )

    def evaluation_report(self) -> EvaluationReport:
        return EvaluationReport(
            schema_version=self.report_schema_version,
            evaluator_id=self.evaluator_id,
            validity=self.validity,
            quality=self.quality,
            combined_score=self.combined_score,
            detailed_scores=self.detailed_scores,
            error_info=self.error_info,
        )


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    code_path: str
    parent_id: str | None
    generation: int
    iteration: int
    strategy: Literal["loop", "population", "openevolve"]
    island_id: int | None
    evaluation: EvaluationReport
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    # Optional additive projection.  Historical/manual candidates intentionally leave these
    # fields unset; newly persisted ordinary candidates always populate them.
    source_sha256: str | None = None
    receipt_sha256: str | None = None
    integrity: dict[str, Any] | None = None
    bundle_evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        _safe_relative_path(self.code_path, "candidate code path")
        if self.parent_id is not None:
            _safe_id(self.parent_id, "parent_id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("iteration must be a non-negative integer")
        if self.strategy not in EVOLUTION_STRATEGIES:
            raise ValueError("candidate strategy is unsupported")
        if self.island_id is not None and (isinstance(self.island_id, bool) or not isinstance(self.island_id, int) or self.island_id < 0):
            raise ValueError("island_id must be a non-negative integer or null")
        encoded = json.dumps(self.metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise ValueError("candidate metadata exceeds the bounded metadata limit")
        if self.source_sha256 is not None and (
            not isinstance(self.source_sha256, str) or not _SHA256.fullmatch(self.source_sha256)
        ):
            raise ValueError("candidate source_sha256 must be a lowercase SHA-256 digest or null")
        if self.receipt_sha256 is not None and (
            not isinstance(self.receipt_sha256, str) or not _SHA256.fullmatch(self.receipt_sha256)
        ):
            raise ValueError("candidate receipt_sha256 must be a lowercase SHA-256 digest or null")
        if (self.source_sha256 is None) != (self.receipt_sha256 is None):
            raise ValueError("candidate source and receipt digests must be supplied together")
        if self.bundle_evidence is not None:
            from .bundle_evolution import validate_bundle_evidence_shape

            if self.source_sha256 is None or self.receipt_sha256 is None or self.integrity is None:
                raise ValueError("candidate bundle evidence requires receipt digests and integrity")
            object.__setattr__(self, "bundle_evidence", validate_bundle_evidence_shape(self.bundle_evidence))
        if self.integrity is not None:
            if not isinstance(self.integrity, dict):
                raise ValueError("candidate integrity projection must be an object or null")
            encoded_integrity = json.dumps(
                self.integrity,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded_integrity) > 4 * 1024:
                raise ValueError("candidate integrity projection exceeds the bounded limit")
            if self.source_sha256 is None or self.receipt_sha256 is None:
                raise ValueError("candidate integrity projection requires receipt digests")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_id": self.candidate_id,
            "code_path": self.code_path,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "strategy": self.strategy,
            "island_id": self.island_id,
            "evaluation": self.evaluation.to_dict(),
            "metadata": self.metadata,
            "created_at": self.created_at,
        }
        if self.source_sha256 is not None:
            payload["source_sha256"] = self.source_sha256
            payload["receipt_sha256"] = self.receipt_sha256
            payload["integrity"] = self.integrity or {}
        if self.bundle_evidence is not None:
            payload["bundle_evidence"] = self.bundle_evidence
        return payload

    @classmethod
    def from_dict(cls, value: object) -> Candidate:
        if not isinstance(value, dict):
            raise EvolutionError("candidate record must be an object")
        return cls(
            candidate_id=value.get("candidate_id"),  # type: ignore[arg-type]
            code_path=value.get("code_path"),  # type: ignore[arg-type]
            parent_id=value.get("parent_id"),  # type: ignore[arg-type]
            generation=value.get("generation"),  # type: ignore[arg-type]
            iteration=value.get("iteration"),  # type: ignore[arg-type]
            strategy=value.get("strategy"),  # type: ignore[arg-type]
            island_id=value.get("island_id"),  # type: ignore[arg-type]
            evaluation=EvaluationReport.from_dict(value.get("evaluation")),
            metadata=value.get("metadata", {}),  # type: ignore[arg-type]
            created_at=value.get("created_at", time.time()),  # type: ignore[arg-type]
            source_sha256=value.get("source_sha256"),  # type: ignore[arg-type]
            receipt_sha256=value.get("receipt_sha256"),  # type: ignore[arg-type]
            integrity=value.get("integrity"),  # type: ignore[arg-type]
            bundle_evidence=value.get("bundle_evidence"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    status: Literal["running", "completed", "stagnated", "cancelled", "failed"]
    iterations: int
    evaluated_candidates: int
    valid_candidates: int
    best_candidate_id: str | None
    best_score: float | None
    archive_path: str
    error: str | None = None
    best_candidate_path: str | None = None

    def __post_init__(self) -> None:
        # ``loop`` remains representable for read-only historical results.  Runtime callers may
        # construct only one of the known active or historical identities; an arbitrary label must
        # never flow into materialization or a benchmark projection as if it were a strategy.
        if self.strategy not in EVOLUTION_STRATEGIES:
            raise ValueError("strategy result is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "iterations": self.iterations,
            "evaluated_candidates": self.evaluated_candidates,
            "valid_candidates": self.valid_candidates,
            "best_candidate_id": self.best_candidate_id,
            "best_score": self.best_score,
            "best_candidate_path": self.best_candidate_path,
            "archive_path": self.archive_path,
            "error": _bounded_error(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class PopulationState:
    """JSON-safe view of the mutable active population persisted by ``PopulationStrategy``."""

    iteration: int
    population_size: int
    offspring_per_iteration: int
    num_islands: int
    active_ids: dict[str, tuple[str, ...]]
    best_candidate_id: str | None = None
    rng_seed: int | None = None
    last_migration_iteration: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("population iteration must be a non-negative integer")
        config = PopulationConfig(
            population_size=self.population_size,
            offspring_per_iteration=self.offspring_per_iteration,
            num_islands=self.num_islands,
            rng_seed=self.rng_seed,
        )
        del config
        if self.best_candidate_id is not None:
            _safe_id(self.best_candidate_id, "best_candidate_id")
        if isinstance(self.last_migration_iteration, bool) or not isinstance(self.last_migration_iteration, int) or self.last_migration_iteration < 0:
            raise ValueError("last_migration_iteration must be a non-negative integer")
        expected = {str(index) for index in range(self.num_islands)}
        if set(self.active_ids) != expected:
            raise ValueError("active_ids must contain one entry for every island")
        if sum(len(ids) for ids in self.active_ids.values()) > self.population_size:
            raise ValueError("active population exceeds population_size")
        all_ids = [candidate_id for ids in self.active_ids.values() for candidate_id in ids]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("active candidate IDs must be unique")
        for ids in self.active_ids.values():
            for candidate_id in ids:
                _safe_id(candidate_id, "active candidate id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "active_ids": {key: list(value) for key, value in self.active_ids.items()},
            "best_candidate_id": self.best_candidate_id,
            "rng_seed": self.rng_seed,
            "last_migration_iteration": self.last_migration_iteration,
        }


@dataclass(frozen=True)
class OffspringOutcome:
    """One durable, prose-free terminal result for a configured offspring attempt."""

    iteration: int
    attempt: int
    island_id: int
    code: Literal[
        "evaluated",
        "candidate_failed",
        "evaluator_timeout",
        "worker_unknown",
        "run_failed",
    ]
    candidate_id: str | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("offspring outcome schema is unsupported")
        if (
            isinstance(self.iteration, bool)
            or not isinstance(self.iteration, int)
            or self.iteration < 1
        ):
            raise ValueError("offspring outcome iteration is invalid")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or not 0 <= self.attempt < 256
        ):
            raise ValueError("offspring outcome attempt is invalid")
        if (
            isinstance(self.island_id, bool)
            or not isinstance(self.island_id, int)
            or not 0 <= self.island_id < 64
        ):
            raise ValueError("offspring outcome island is invalid")
        if self.code not in _OFFSPRING_OUTCOME_CODES:
            raise ValueError("offspring outcome code is invalid")
        if self.code == "evaluated":
            _safe_id(self.candidate_id, "offspring outcome candidate_id")
        elif self.candidate_id is not None:
            raise ValueError("failed offspring outcome must not claim a candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "iteration": self.iteration,
            "attempt": self.attempt,
            "island_id": self.island_id,
            "code": self.code,
            "candidate_id": self.candidate_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> OffspringOutcome:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "iteration",
            "attempt",
            "island_id",
            "code",
            "candidate_id",
        }:
            raise ValueError("offspring outcome record is invalid")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            iteration=value["iteration"],  # type: ignore[arg-type]
            attempt=value["attempt"],  # type: ignore[arg-type]
            island_id=value["island_id"],  # type: ignore[arg-type]
            code=value["code"],  # type: ignore[arg-type]
            candidate_id=value["candidate_id"],  # type: ignore[arg-type]
        )


class EvolutionStrategy(Protocol):
    """Runtime-neutral strategy boundary shared by native and external implementations."""

    name: str

    def run(self) -> StrategyResult:
        ...

    def resume(self) -> StrategyResult:
        ...


@dataclass(frozen=True)
class GenerationRequest:
    iteration: int
    parent: Candidate | None
    inspirations: tuple[Candidate, ...]
    archive: tuple[Candidate, ...]
    workspace: Path
    # Reserved by the native strategy before generation starts.  External callers may omit it;
    # durable controller runs provide it so completion receipts can bind the parser result.
    candidate_id: str | None = None


class CandidateGenerator(Protocol):
    def __call__(self, request: GenerationRequest) -> CandidateDraft | Sequence[CandidateDraft]:
        """Return one or more candidate drafts for an isolated generation context."""


class CandidateEvaluator(Protocol):
    def __call__(self, candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport | dict[str, Any]:
        """Evaluate a candidate and return the validity-first report."""


class SeedEvidenceRecord(Protocol):
    """JSON projection supplied by the verified seed admission boundary."""

    def to_dict(self) -> dict[str, Any]:
        ...


class AdmittedSeedInput(Protocol):
    """Structural input accepted from ``seed_handoff.AdmittedSeed`` without importing it."""

    candidate_id: str
    draft: CandidateDraft
    evaluation: EvaluationReport
    receipt: SeedEvidenceRecord
    provenance: SeedEvidenceRecord
    handoff_sha256: str
    generation: int
    iteration: int
    parent_id: None
    strategy: Literal["population"]
    island_id: int


class CommandCandidateGenerator:
    """Adapt an explicit local command that emits a draft as JSON or plain source text."""

    def __init__(self, command: Sequence[str], timeout_seconds: float = 900.0) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("generator command must be a non-empty bounded argument sequence")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("generator command must start with an existing absolute executable path")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def __call__(self, request: GenerationRequest) -> CandidateDraft | Sequence[CandidateDraft]:
        request_dir = request.workspace / "evolution" / "external" / "generator"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"request-{request.iteration:04d}.json"
        payload = {
            "iteration": request.iteration,
            "parent": request.parent.to_dict() if request.parent else None,
            "inspirations": [item.to_dict() for item in request.inspirations],
            "archive": [item.to_dict() for item in request.archive[-32:]],
            "workspace": str(request.workspace),
        }
        if request.parent is not None and request.parent.bundle_evidence is not None:
            from .bundle_evolution import read_candidate_source_files

            payload["parent_source_files"] = read_candidate_source_files(request.workspace, request.parent)
        request_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [*self.command, str(request_path)],
                cwd=request.workspace,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EvolutionError(f"candidate generator timed out after {self.timeout_seconds:g}s") from exc
        except OSError as exc:
            raise EvolutionError(_bounded_error(exc)) from exc
        if completed.returncode != 0:
            raise EvolutionError(_bounded_error(completed.stderr or completed.stdout or f"generator exited with {completed.returncode}"))
        output = completed.stdout.strip()
        if not output:
            raise EvolutionError("candidate generator returned empty output")
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            return CandidateDraft(output)
        def draft_from_object(item: dict[str, Any]) -> CandidateDraft:
            if "files" in item:
                if "source" in item or "filename" in item:
                    raise EvolutionError("bundle_candidate_draft_invalid")
                return CandidateDraft.from_files(item["files"], item.get("entrypoint"), item.get("metadata", {}))
            return CandidateDraft(item["source"], item.get("filename", "candidate.py"), item.get("metadata", {}))

        if isinstance(decoded, dict) and ("source" in decoded or "files" in decoded):
            return draft_from_object(decoded)
        if isinstance(decoded, list):
            return tuple(
                draft_from_object(item)
                for item in decoded
                if isinstance(item, dict) and ("source" in item or "files" in item)
            )
        raise EvolutionError("candidate generator JSON must contain source or a source array")


class CommandCandidateEvaluator:
    """Adapt an explicit local command that emits an EvaluationReport JSON object."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float = 900.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("evaluator command must be a non-empty bounded argument sequence")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("evaluator command must start with an existing absolute executable path")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("candidate evaluator timeout must be positive")
        self.command = command
        self.timeout_seconds = float(timeout_seconds)
        self._remaining_timeout: Callable[[str], float] | None = None
        if environment is None:
            self.environment = None
        else:
            if len(environment) > 64:
                raise ValueError("candidate evaluator environment has too many entries")
            normalized_environment: dict[str, str] = {}
            for key, value in environment.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or "\x00" in key
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    raise ValueError("candidate evaluator environment is invalid")
                if len(key.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 4_096:
                    raise ValueError("candidate evaluator environment entry is too large")
                normalized_environment[key] = value
            self.environment = normalized_environment

    def set_remaining_timeout(self, callback: Callable[[str], float] | None) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("remaining timeout callback must be callable or None")
        self._remaining_timeout = callback

    def __call__(self, candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        timeout = self.timeout_seconds
        if self._remaining_timeout is not None:
            remaining = self._remaining_timeout("evaluation")
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(float(remaining)) or remaining <= 0:
                raise EvolutionError("automatic solve execution budget exhausted")
            timeout = min(timeout, float(remaining))
        try:
            completed = subprocess.run(
                [*self.command, str(candidate_path)],
                cwd=candidate_path.parent,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if self._remaining_timeout is not None:
                self._remaining_timeout("evaluation")
            raise EvolutionError(f"candidate evaluator timed out after {self.timeout_seconds:g}s") from exc
        except OSError as exc:
            if self._remaining_timeout is not None:
                self._remaining_timeout("evaluation")
            raise EvolutionError(_bounded_error(exc)) from exc
        if self._remaining_timeout is not None:
            self._remaining_timeout("evaluation")
        if completed.returncode != 0:
            raise EvolutionError(_bounded_error(completed.stderr or completed.stdout or f"evaluator exited with {completed.returncode}"))
        if len(completed.stdout.encode("utf-8")) > MAX_EXTERNAL_RESULT_BYTES:
            raise EvolutionError("candidate evaluator output exceeds the bounded result size")
        try:
            return _report(json.loads(completed.stdout))
        except (json.JSONDecodeError, TypeError, ValueError, EvolutionError) as exc:
            raise EvolutionError("candidate evaluator did not return a valid evaluation report") from exc


@dataclass(frozen=True)
class EvolutionContext:
    contract: AlgorithmProblemContract
    workspace: Path
    generate: CandidateGenerator
    evaluate: CandidateEvaluator
    config: EvolutionConfig = field(default_factory=EvolutionConfig)
    cancelled: Callable[[], bool] = lambda: False
    # Optional audit hook used by the SQLite controller.  The strategy remains runtime-neutral;
    # callers that do not need a ledger can leave this unset.
    observe: Callable[[str, dict[str, Any]], None] = lambda event, payload: None
    initial_seeds: Sequence[AdmittedSeedInput] = ()
    # Optional explicit identities for ordinary candidate receipts.  They are separate from the
    # strategy knobs so a controller can bind seed/evaluator authority without changing legacy
    # configuration JSON.  ``None`` selects the documented native protocol identity.
    evaluator_kind: str | None = None
    dependency_sha256: str | None = None
    environment_sha256: str | None = None
    bundle_pipeline: Any | None = None
    # Process-local operational budget hook. It is deliberately not part of persisted config or
    # candidate identity; automatic solve binds the same monotonic deadline to every phase.
    remaining_timeout: Callable[[str], float] | None = None
    # Optional local subprocess ownership hooks used by automatic lifecycle execution.
    process_observer: Callable[[int, int | None], None] | None = None
    process_released: Callable[[int, int | None], None] | None = None
    continuation_guard: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        try:
            seeds = tuple(self.initial_seeds)
        except TypeError as exc:
            raise TypeError("initial_seeds must be a bounded sequence") from exc
        if len(seeds) > 32:
            raise ValueError("initial_seeds exceeds the bounded seed limit")
        object.__setattr__(self, "initial_seeds", seeds)
        for name, value in (
            ("dependency_sha256", self.dependency_sha256),
            ("environment_sha256", self.environment_sha256),
        ):
            if value is not None and (
                not isinstance(value, str) or not _SHA256.fullmatch(value)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest or null")
        if self.evaluator_kind is not None and (
            not isinstance(self.evaluator_kind, str)
            or not _SAFE_ID.fullmatch(self.evaluator_kind)
            or _SECRET_OUTPUT.search(self.evaluator_kind)
        ):
            raise ValueError("evaluator_kind must be a safe identifier or null")


@dataclass(frozen=True)
class CandidateIntegrityAuthority:
    """Uniform authority tuple persisted with a native evolution run."""

    schema_version: str
    contract_sha256: str
    evaluator_kind: str
    evaluator_fingerprint: str
    dependency_sha256: str
    environment_sha256: str
    runner_fingerprint: str
    generator_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_INTEGRITY_SCHEMA_VERSION:
            raise EvolutionError("ordinary_candidate_integrity_invalid")
        for name in (
            "contract_sha256",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "runner_fingerprint",
            "generator_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise EvolutionError("ordinary_candidate_integrity_invalid")
        if (
            not isinstance(self.evaluator_kind, str)
            or not _SAFE_ID.fullmatch(self.evaluator_kind)
            or _SECRET_OUTPUT.search(self.evaluator_kind)
        ):
            raise EvolutionError("ordinary_candidate_integrity_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_sha256": self.contract_sha256,
            "evaluator_kind": self.evaluator_kind,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
            "runner_fingerprint": self.runner_fingerprint,
            "generator_fingerprint": self.generator_fingerprint,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> CandidateIntegrityAuthority:
        if not isinstance(value, dict):
            raise EvolutionError("ordinary_candidate_integrity_invalid")
        required = {
            "schema_version",
            "contract_sha256",
            "evaluator_kind",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
            "runner_fingerprint",
            "generator_fingerprint",
        }
        if set(value) != required:
            raise EvolutionError("ordinary_candidate_integrity_invalid")
        return cls(
            schema_version=value["schema_version"],
            contract_sha256=value["contract_sha256"],
            evaluator_kind=value["evaluator_kind"],
            evaluator_fingerprint=value["evaluator_fingerprint"],
            dependency_sha256=value["dependency_sha256"],
            environment_sha256=value["environment_sha256"],
            runner_fingerprint=value["runner_fingerprint"],
            generator_fingerprint=value["generator_fingerprint"],
        )


def _seed_authority_hint(context: EvolutionContext, name: str) -> object | None:
    """Read an authority field from the first admitted seed without importing its concrete type."""

    if not context.initial_seeds:
        return None
    try:
        receipt = context.initial_seeds[0].receipt
        payload = receipt.to_dict()
    except (AttributeError, TypeError, ValueError):
        return None
    return payload.get(name) if isinstance(payload, dict) else None


def resolve_candidate_integrity_authority(context: EvolutionContext) -> CandidateIntegrityAuthority:
    """Resolve explicit identities, falling back to declared native protocol identities."""

    config = context.config

    def choose(context_value: object | None, config_value: object | None, seed_name: str, fallback: str) -> str:
        if (
            context_value is not None
            and config_value is not None
            and context_value != config_value
        ):
            raise EvolutionError("ordinary_candidate_integrity_invalid")
        for value in (context_value, config_value, _seed_authority_hint(context, seed_name)):
            if value is not None:
                if not isinstance(value, str):
                    raise EvolutionError("ordinary_candidate_integrity_invalid")
                return value
        return fallback

    contract_sha256 = context.contract.digest()
    evaluator_kind = choose(
        context.evaluator_kind,
        config.evaluator_kind,
        "evaluator_kind",
        "native",
    )
    evaluator_fingerprint = choose(
        config.evaluator_fingerprint,
        None,
        "evaluator_fingerprint",
        _native_evaluator_identity(),
    )
    dependency_sha256 = choose(
        context.dependency_sha256,
        config.dependency_sha256,
        "dependency_sha256",
        _native_dependency_identity(),
    )
    environment_sha256 = choose(
        context.environment_sha256,
        config.environment_sha256,
        "environment_sha256",
        _native_environment_identity(),
    )
    runner_fingerprint = choose(
        config.runner_fingerprint,
        None,
        "runner_fingerprint",
        _native_runner_identity(),
    )
    generator_fingerprint = choose(
        config.generator_fingerprint,
        None,
        "generator_fingerprint",
        _native_generator_identity(),
    )
    return CandidateIntegrityAuthority(
        schema_version=CANDIDATE_INTEGRITY_SCHEMA_VERSION,
        contract_sha256=contract_sha256,
        evaluator_kind=evaluator_kind,
        evaluator_fingerprint=evaluator_fingerprint,
        dependency_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
        runner_fingerprint=runner_fingerprint,
        generator_fingerprint=generator_fingerprint,
    )


_SEED_RECEIPT_FIELDS = frozenset(
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
_SEED_PROVENANCE_FIELDS = frozenset(
    {
        "origin_kind",
        "producer_id",
        "producer_fingerprint",
        "producer_run_id",
        "material_refs",
        "external_evidence",
    }
)
_SEED_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "source_sha256",
        "contract_sha256",
        "evaluator_kind",
        "evaluator_fingerprint",
        "dependency_sha256",
        "environment_sha256",
        "lineage",
        "provenance",
        "provenance_sha256",
        "handoff_sha256",
        "receipt_sha256",
    }
)


def _canonical_seed_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return encoded.encode("utf-8")


def _canonical_seed_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_seed_bytes(value)).hexdigest()


def _seed_evidence_mapping(
    value: SeedEvidenceRecord,
    *,
    fields: frozenset[str],
) -> dict[str, Any]:
    payload = value.to_dict()
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("seed evidence schema mismatch")
    encoded = _canonical_seed_bytes(payload)
    if len(encoded) > MAX_ARCHIVE_LINE_BYTES:
        raise ValueError("seed evidence exceeds the bounded record size")
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True)
class _PreparedInitialSeed:
    candidate: Candidate
    source: str
    filename: str
    receipt: dict[str, Any]
    provenance: dict[str, Any]
    handoff_sha256: str

    @property
    def candidate_dir(self) -> str:
        return f"candidates/{self.candidate.candidate_id}"


def _prepare_initial_seed(
    value: AdmittedSeedInput,
    *,
    canonical_strategy: Literal["population", "openevolve"] = "population",
) -> _PreparedInitialSeed:
    if canonical_strategy not in {"population", "openevolve"}:
        raise ValueError("verified seed canonical strategy is invalid")
    candidate_id = _safe_id(value.candidate_id, "verified seed candidate_id")
    if not isinstance(value.draft, CandidateDraft):
        raise TypeError("verified seed draft is invalid")
    if value.draft.source_files is not None:
        raise ValueError("verified seed requires a single-file draft")
    if not isinstance(value.evaluation, EvaluationReport):
        raise TypeError("verified seed evaluation is invalid")
    if value.evaluation.validity != 1 or not math.isfinite(
        float(value.evaluation.combined_score)
    ):
        raise ValueError("verified seed must have a usable local evaluation")
    if value.evaluation.error_info:
        raise ValueError("verified seed evaluation must not persist evaluator error prose")
    if (
        value.generation != 0
        or value.iteration != 0
        or value.parent_id is not None
        or value.strategy != "population"
        or isinstance(value.island_id, bool)
        or not isinstance(value.island_id, int)
        or value.island_id < 0
    ):
        raise ValueError("verified seed population fields are invalid")

    filename = _safe_relative_path(value.draft.filename, "verified seed filename")
    if Path(filename).name in {"record.json", "receipt.json"}:
        raise ValueError("verified seed filename is reserved")
    source = value.draft.source
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    receipt = _seed_evidence_mapping(value.receipt, fields=_SEED_RECEIPT_FIELDS)
    provenance = _seed_evidence_mapping(value.provenance, fields=_SEED_PROVENANCE_FIELDS)

    if receipt["schema_version"] != "1" or receipt["candidate_id"] != candidate_id:
        raise ValueError("verified seed receipt identity mismatch")
    for field_name in (
        "source_sha256",
        "contract_sha256",
        "evaluator_fingerprint",
        "dependency_sha256",
        "environment_sha256",
        "receipt_sha256",
    ):
        if not isinstance(receipt[field_name], str) or not _SHA256.fullmatch(
            receipt[field_name]
        ):
            raise ValueError("verified seed receipt digest is invalid")
    if receipt["source_sha256"] != source_sha256:
        raise ValueError("verified seed source digest mismatch")
    receipt_payload = {
        key: item for key, item in receipt.items() if key != "receipt_sha256"
    }
    if receipt["receipt_sha256"] != _canonical_seed_sha256(receipt_payload):
        raise ValueError("verified seed receipt digest mismatch")
    if (
        receipt["validity"] != 1
        or isinstance(receipt["combined_score"], bool)
        or not isinstance(receipt["combined_score"], (int, float))
        or not math.isfinite(float(receipt["combined_score"]))
        or float(receipt["combined_score"]) < 0
    ):
        raise ValueError("verified seed receipt score is invalid")
    if (
        receipt["report_schema_version"] != value.evaluation.schema_version
        or receipt["evaluator_id"] != value.evaluation.evaluator_id
        or receipt["validity"] != value.evaluation.validity
        or receipt["quality"] != value.evaluation.quality
        or receipt["combined_score"] != value.evaluation.combined_score
        or receipt["detailed_scores"] != value.evaluation.detailed_scores
        or [item.get("code") for item in receipt["error_info"]]
        != [item.get("code") for item in value.evaluation.error_info]
    ):
        raise ValueError("verified seed receipt does not describe its local evaluation")
    if receipt["error_info"]:
        raise ValueError("verified seed receipt must not contain evaluator error prose")

    if provenance["origin_kind"] not in {"local", "external"}:
        raise ValueError("verified seed provenance origin is invalid")
    _safe_id(provenance["producer_id"], "verified seed producer_id")
    producer_run_id = provenance["producer_run_id"]
    if producer_run_id is not None:
        _safe_id(producer_run_id, "verified seed producer_run_id")
    if not isinstance(provenance["producer_fingerprint"], str) or not _SHA256.fullmatch(
        provenance["producer_fingerprint"]
    ):
        raise ValueError("verified seed producer fingerprint is invalid")
    if provenance["origin_kind"] == "external" and receipt["evaluator_kind"] != "exact_harness":
        raise ValueError("external verified seed requires the exact harness")
    provenance_sha256 = _canonical_seed_sha256(provenance)

    metadata = value.draft.metadata
    if not isinstance(metadata, dict):
        raise TypeError("verified seed metadata is invalid")
    handoff = metadata.get("seed_handoff")
    if not isinstance(handoff, dict) or set(handoff) != _SEED_METADATA_FIELDS:
        raise ValueError("verified seed metadata schema mismatch")
    if (
        handoff["schema_version"] != "1"
        or handoff["candidate_id"] != candidate_id
        or handoff["source_sha256"] != source_sha256
        or handoff["contract_sha256"] != receipt["contract_sha256"]
        or handoff["evaluator_kind"] != receipt["evaluator_kind"]
        or handoff["evaluator_fingerprint"] != receipt["evaluator_fingerprint"]
        or handoff["dependency_sha256"] != receipt["dependency_sha256"]
        or handoff["environment_sha256"] != receipt["environment_sha256"]
        or handoff["provenance_sha256"] != provenance_sha256
        or handoff["receipt_sha256"] != receipt["receipt_sha256"]
    ):
        raise ValueError("verified seed metadata identity mismatch")
    lineage = handoff["lineage"]
    if not isinstance(lineage, list) or any(not isinstance(item, str) for item in lineage):
        raise ValueError("verified seed lineage is invalid")
    identity_payload = {
        "schema_version": "1",
        "source_sha256": source_sha256,
        "contract_sha256": receipt["contract_sha256"],
        "evaluator_kind": receipt["evaluator_kind"],
        "evaluator_fingerprint": receipt["evaluator_fingerprint"],
        "dependency_sha256": receipt["dependency_sha256"],
        "environment_sha256": receipt["environment_sha256"],
        "lineage": lineage,
    }
    if candidate_id != f"seed-{_canonical_seed_sha256(identity_payload)}":
        raise ValueError("verified seed derived identity mismatch")
    projection = {
        "origin_kind": provenance["origin_kind"],
        "producer_id": provenance["producer_id"],
        "producer_fingerprint": provenance["producer_fingerprint"],
        "producer_run_id": provenance["producer_run_id"],
        "material_refs_sha256": _canonical_seed_sha256(provenance["material_refs"]),
        "external_evidence_sha256": _canonical_seed_sha256(
            provenance["external_evidence"]
        ),
    }
    if handoff["provenance"] != projection:
        raise ValueError("verified seed provenance projection mismatch")
    expected_handoff = _canonical_seed_sha256(
        {
            "schema_version": "1",
            "candidate_id": candidate_id,
            "provenance": provenance,
        }
    )
    if (
        not isinstance(value.handoff_sha256, str)
        or not _SHA256.fullmatch(value.handoff_sha256)
        or value.handoff_sha256 != expected_handoff
        or handoff["handoff_sha256"] != expected_handoff
    ):
        raise ValueError("verified seed handoff fingerprint mismatch")

    candidate = Candidate(
        candidate_id=candidate_id,
        code_path=(Path("evolution") / "candidates" / candidate_id / filename).as_posix(),
        parent_id=None,
        generation=0,
        iteration=0 if canonical_strategy == "population" else 1,
        strategy=canonical_strategy,
        island_id=value.island_id if canonical_strategy == "population" else None,
        evaluation=value.evaluation,
        metadata=metadata,
    )
    if len(_canonical_seed_bytes(candidate.to_dict())) > MAX_ARCHIVE_LINE_BYTES:
        raise ValueError("verified seed candidate record is too large")
    return _PreparedInitialSeed(
        candidate=candidate,
        source=source,
        filename=filename,
        receipt=receipt,
        provenance=provenance,
        handoff_sha256=expected_handoff,
    )


def _prepare_initial_seeds(
    values: Sequence[AdmittedSeedInput],
    *,
    canonical_strategy: Literal["population", "openevolve"] = "population",
) -> tuple[_PreparedInitialSeed, ...]:
    try:
        seeds = tuple(values)
        if not seeds or len(seeds) > 32:
            raise ValueError("verified seed batch size is invalid")
        prepared = tuple(
            _prepare_initial_seed(seed, canonical_strategy=canonical_strategy) for seed in seeds
        )
        candidate_ids = [item.candidate.candidate_id for item in prepared]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("verified seed candidate IDs must be unique")
        authority = {
            (
                item.receipt["contract_sha256"],
                item.receipt["evaluator_kind"],
                item.receipt["evaluator_fingerprint"],
                item.receipt["dependency_sha256"],
                item.receipt["environment_sha256"],
            )
            for item in prepared
        }
        if len(authority) != 1:
            raise ValueError("verified seed authority must be uniform")
        return prepared
    except Exception as exc:
        raise EvolutionError("verified_seed_invalid") from exc


def _seed_admission_summary(
    prepared: Sequence[_PreparedInitialSeed],
) -> dict[str, Any]:
    records = [
        {
            "candidate_id": item.candidate.candidate_id,
            "receipt_sha256": item.receipt["receipt_sha256"],
            "handoff_sha256": item.handoff_sha256,
            "provenance_sha256": _canonical_seed_sha256(item.provenance),
        }
        for item in sorted(prepared, key=lambda item: item.candidate.candidate_id)
    ]
    payload = {
        "schema_version": "1",
        "seeds": records,
    }
    return {**payload, "admission_sha256": _canonical_seed_sha256(payload)}


class CandidateArchive:
    """Append-only candidate records and atomic strategy state for one run."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        requested_strategy: str | None = None,
        read_only: bool = False,
    ) -> None:
        if type(read_only) is not bool:
            raise EvolutionError("evolution_archive_read_only_invalid")
        self.read_only = read_only
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink():
            raise EvolutionError("evolution workspace must not be a symlink")
        self.workspace = raw_workspace.resolve()
        self.root = self.workspace / "evolution"
        self.candidates_root = self.root / "candidates"
        self.archive_path = self.root / "archive.jsonl"
        self.offspring_outcomes_path = self.root / "offspring-outcomes.jsonl"
        self.state_path = self.root / "state.json"
        self.seed_commit_path = self.root / "seed-commit.json"
        self.seed_stage_path = self.workspace / _SEED_STAGE_NAME
        self.seed_backup_path = self.workspace / _SEED_BACKUP_NAME
        self._producer_publication_inspection = False
        self._guard_producer_publication_recovery()
        if read_only:
            self._inspect_read_only_layout()
        self._preflight_seed_recovery_strategy(requested_strategy)
        if not read_only:
            raw_workspace.mkdir(parents=True, exist_ok=True)
            self._recover_seed_publication()
        for path in (self.root, self.candidates_root):
            if path.is_symlink():
                raise EvolutionError("evolution archive directory must not be a symlink")

    def _inspect_read_only_layout(self) -> None:
        """Inspect an existing archive without allocating or recovering any directory."""
        if not self.workspace.is_dir():
            raise EvolutionError("evolution_archive_workspace_missing")
        for path in (self.root, self.candidates_root):
            if self._path_present(path) and (path.is_symlink() or not path.is_dir()):
                raise EvolutionError("evolution_archive_directory_invalid")
        try:
            with os.scandir(self.workspace) as entries:
                if any(
                    entry.name.startswith(".evolution-seed-stage-")
                    or entry.name.startswith(".evolution-seed-backup-")
                    for entry in entries
                ):
                    raise EvolutionError("evolution_archive_recovery_required")
        except OSError as exc:
            raise EvolutionError("evolution_archive_directory_invalid") from exc

    def _require_writable(self) -> None:
        self._guard_producer_publication_recovery()
        if self.read_only:
            raise EvolutionError("evolution_archive_read_only")

    def _guard_producer_publication_recovery(self) -> None:
        """Reject an archive whose producer publication has an unresolved commit marker.

        The transaction implementation may create a private read-only inspection view while it
        holds the workspace publication lock.  That view sets the private inspection flag before
        invoking archive validators; no public constructor argument can bypass this guard.
        """

        if getattr(self, "_producer_publication_inspection", False):
            return
        marker = getattr(self, "root", Path(".")) / _PRODUCER_PUBLICATION_MARKER_NAME
        try:
            present = marker.exists() or marker.is_symlink()
        except OSError as exc:
            raise EvolutionError(_PRODUCER_PUBLICATION_RECOVERY_ERROR) from exc
        if present:
            raise EvolutionError(_PRODUCER_PUBLICATION_RECOVERY_ERROR)

    @staticmethod
    def _path_present(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    def _preflight_seed_recovery_strategy(self, requested_strategy: str | None) -> None:
        """Read every visible recovery tree before mkdir, replace, or cleanup.

        A strategy constructor supplies its identity so recovery artifacts cannot cross an
        active strategy boundary before callbacks can be bound. Ordinary root-only validation
        remains with the existing resume paths and their more specific integrity errors.
        """

        if requested_strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if requested_strategy is not None and requested_strategy not in ACTIVE_EVOLUTION_STRATEGIES:
            raise EvolutionError("unsupported candidate strategy")
        recovering = self._path_present(self.seed_stage_path) or self._path_present(
            self.seed_backup_path
        )
        if not recovering:
            return

        operational: set[str] = set()
        contracts: set[str] = set()
        operational_error: str | None = None
        contract_error: str | None = None
        for tree in (self.root, self.seed_stage_path, self.seed_backup_path):
            if not self._path_present(tree):
                continue
            # The same read-only evidence parser is used by all archive writers. Repoint a
            # temporary view rather than changing this archive's root during the scan.
            view = CandidateArchive.__new__(CandidateArchive)
            view.workspace = self.workspace
            view.root = tree
            view.candidates_root = tree / "candidates"
            view.archive_path = tree / "archive.jsonl"
            view.offspring_outcomes_path = tree / "offspring-outcomes.jsonl"
            view.state_path = tree / "state.json"
            view.seed_commit_path = tree / "seed-commit.json"
            found, tagged_contracts, found_error, tagged_contract_error = (
                view._workspace_strategy_evidence()
            )
            operational.update(found)
            contracts.update(tagged_contracts)
            operational_error = operational_error or found_error
            contract_error = contract_error or tagged_contract_error

        if "loop" in operational or "loop" in contracts:
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if (
            operational_error is not None
            or contract_error is not None
            or len(operational) > 1
            or len(contracts) > 1
        ):
            raise EvolutionError(
                operational_error or contract_error or _WORKSPACE_STRATEGY_INVALID
            )
        if requested_strategy is not None and operational and requested_strategy not in operational:
            raise EvolutionError(_WORKSPACE_STRATEGY_MISMATCH)

    @classmethod
    def preflight_new_run_workspace(
        cls,
        workspace: str | Path,
        contract: AlgorithmProblemContract,
    ) -> bool:
        """Check an explicit workspace without creating, recovering, or rewriting it.

        A new ledger run may reuse an absent/empty evolution directory or the exact canonical
        contract-only prefix left by an interrupted setup. Any operational or unrecognized
        evolution evidence belongs to an existing run and must be handled through resume.
        """

        if not isinstance(contract, AlgorithmProblemContract):
            raise TypeError("contract must be an AlgorithmProblemContract")
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink() or (
            raw_workspace.exists() and not raw_workspace.is_dir()
        ):
            raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
        if not raw_workspace.exists():
            return False

        try:
            workspace_entries = tuple(raw_workspace.iterdir())
        except OSError as exc:
            raise EvolutionError(_WORKSPACE_STRATEGY_INVALID) from exc
        if any(
            path.name.startswith(".evolution-seed-stage-")
            or path.name.startswith(".evolution-seed-backup-")
            for path in workspace_entries
        ):
            raise EvolutionError("verified_seed_recovery_ambiguous")

        view = cls.__new__(cls)
        view.workspace = raw_workspace.resolve()
        view.root = view.workspace / "evolution"
        view.candidates_root = view.root / "candidates"
        view.archive_path = view.root / "archive.jsonl"
        view.offspring_outcomes_path = view.root / "offspring-outcomes.jsonl"
        view.state_path = view.root / "state.json"
        view.seed_commit_path = view.root / "seed-commit.json"
        view.seed_stage_path = view.workspace / _SEED_STAGE_NAME
        view.seed_backup_path = view.workspace / _SEED_BACKUP_NAME

        if not cls._path_present(view.root):
            return False
        if view.root.is_symlink() or not view.root.is_dir():
            raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)

        # Inspect recognized evidence first so a historical loop keeps its fixed retirement code.
        view._guard_active_write(contract.evolution.strategy)
        try:
            root_entries = tuple(view.root.iterdir())
        except OSError as exc:
            raise EvolutionError(_WORKSPACE_STRATEGY_INVALID) from exc
        if not root_entries:
            return False
        if len(root_entries) != 1 or root_entries[0].name != "contract.json":
            raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
        _, stored_digest = view._canonical_contract_snapshot(root_entries[0])
        if stored_digest != contract.digest():
            raise EvolutionError(_WORKSPACE_STRATEGY_MISMATCH)
        return True

    @staticmethod
    def _canonical_contract_snapshot(path: Path) -> tuple[bytes, str]:
        try:
            if path.is_symlink() or not path.is_file():
                raise EvolutionError("verified_seed_contract_invalid")
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise EvolutionError("verified_seed_contract_invalid")
            content = path.read_bytes()
            contract = AlgorithmProblemContract.from_dict(
                json.loads(content.decode("utf-8"))
            )
            canonical = (
                json.dumps(
                    contract.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            if content != canonical:
                raise EvolutionError("verified_seed_contract_invalid")
            return content, contract.digest()
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("verified_seed_contract_invalid") from exc

    @classmethod
    def _contract_only_snapshot(cls, root: Path) -> tuple[bytes, str]:
        try:
            if root.is_symlink() or not root.is_dir():
                raise EvolutionError("verified_seed_recovery_ambiguous")
            entries = tuple(root.iterdir())
            if len(entries) != 1 or entries[0].name != "contract.json":
                raise EvolutionError("verified_seed_recovery_ambiguous")
            return cls._canonical_contract_snapshot(entries[0])
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError("verified_seed_recovery_ambiguous") from exc

    @staticmethod
    def _reject_seed_tree_links(root: Path) -> None:
        entries = 0
        for current, directories, files in os.walk(root, followlinks=False):
            for name in [*directories, *files]:
                entries += 1
                if entries > 512:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                path = Path(current) / name
                if path.is_symlink():
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                if name in directories and not path.is_dir():
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                if name in files and not path.is_file():
                    raise EvolutionError("verified_seed_recovery_ambiguous")

    @classmethod
    def _complete_seed_tree_contract(cls, root: Path) -> bytes | None:
        """Recognize only a complete, initial seed tree left by the publish transaction."""

        try:
            if root.is_symlink() or not root.is_dir():
                raise EvolutionError("verified_seed_recovery_ambiguous")
            cls._reject_seed_tree_links(root)
            entries = {path.name: path for path in root.iterdir()}
            required = {"candidates", "archive.jsonl", "state.json", "seed-commit.json"}
            allowed = required | {"contract.json"}
            names = set(entries)
            if names != required and names != allowed:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if not entries["candidates"].is_dir() or any(
                not entries[name].is_file()
                for name in ("archive.jsonl", "state.json", "seed-commit.json")
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if (
                entries["state.json"].stat().st_size > MAX_STATE_BYTES
                or entries["seed-commit.json"].stat().st_size > MAX_ARCHIVE_LINE_BYTES
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            marker = _strict_json_loads(
                entries["seed-commit.json"].read_text(encoding="utf-8")
            )
            state = _strict_json_loads(entries["state.json"].read_text(encoding="utf-8"))
            if not isinstance(marker, dict) or set(marker) != {
                "schema_version",
                "admission_sha256",
                "candidate_ids",
                "seed_candidates_sha256",
                "commit_sha256",
            }:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            marker_payload = {
                key: item for key, item in marker.items() if key != "commit_sha256"
            }
            candidate_ids = marker["candidate_ids"]
            if (
                marker["schema_version"] != "1"
                or not isinstance(candidate_ids, list)
                or not candidate_ids
                or len(candidate_ids) > 32
                or candidate_ids != sorted(candidate_ids)
                or len(candidate_ids) != len(set(candidate_ids))
                or any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item) for item in candidate_ids)
                or marker["commit_sha256"] != _canonical_seed_sha256(marker_payload)
                or not isinstance(state, dict)
                or not isinstance(state.get("seed_admission"), dict)
                or state["seed_admission"].get("admission_sha256")
                != marker["admission_sha256"]
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if entries["archive.jsonl"].stat().st_size > MAX_ARCHIVE_LINE_BYTES * 32:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            archive_lines = [
                line
                for line in entries["archive.jsonl"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if any(
                len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                for line in archive_lines
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            candidates = [Candidate.from_dict(_strict_json_loads(line)) for line in archive_lines]
            population_seed_tree = bool(candidates) and all(
                candidate.parent_id is None
                and candidate.generation == 0
                and candidate.iteration == 0
                and candidate.strategy == "population"
                and candidate.island_id is not None
                for candidate in candidates
            )
            openevolve_seed_tree = len(candidates) == 1 and all(
                candidate.parent_id is None
                and candidate.generation == 0
                and candidate.iteration == 1
                and candidate.strategy == "openevolve"
                and candidate.island_id is None
                for candidate in candidates
            )
            expected_strategy = "population" if population_seed_tree else "openevolve"
            expected_iteration = 0 if population_seed_tree else 1
            if (
                [candidate.candidate_id for candidate in candidates] != candidate_ids
                or not (population_seed_tree or openevolve_seed_tree)
                or state.get("strategy") != expected_strategy
                or (
                    "config" in state
                    and (
                        not isinstance(state["config"], dict)
                        or state["config"].get("strategy") != expected_strategy
                    )
                )
                or state.get("iteration") != expected_iteration
                or marker["seed_candidates_sha256"]
                != _canonical_seed_sha256([candidate.to_dict() for candidate in candidates])
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            for candidate in candidates:
                relative = Path(candidate.code_path)
                if not relative.parts or relative.parts[0] != "evolution":
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                source = root.joinpath(*relative.parts[1:])
                candidate_root = entries["candidates"] / candidate.candidate_id
                try:
                    source.relative_to(candidate_root)
                except ValueError as exc:
                    raise EvolutionError("verified_seed_recovery_ambiguous") from exc
                if (
                    not source.is_file()
                    or not (source.parent / "record.json").is_file()
                    or not (source.parent / "receipt.json").is_file()
                ):
                    raise EvolutionError("verified_seed_recovery_ambiguous")
            if "contract.json" not in entries:
                return None
            return cls._canonical_contract_snapshot(entries["contract.json"])[0]
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("verified_seed_recovery_ambiguous") from exc

    @staticmethod
    def _remove_recovery_tree(path: Path) -> None:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise EvolutionError("verified_seed_recovery_failed") from exc

    def _recover_seed_publication(self) -> None:
        self._require_writable()
        reserved = [
            path
            for path in self.workspace.iterdir()
            if (
                path.name.startswith(".evolution-seed-stage-")
                or path.name.startswith(".evolution-seed-backup-")
            )
            and path not in {self.seed_stage_path, self.seed_backup_path}
        ]
        if reserved:
            raise EvolutionError("verified_seed_recovery_ambiguous")

        stage_present = self._path_present(self.seed_stage_path)
        backup_present = self._path_present(self.seed_backup_path)
        root_present = self._path_present(self.root)
        if not stage_present and not backup_present:
            return
        if self.root.is_symlink() or self.seed_stage_path.is_symlink() or self.seed_backup_path.is_symlink():
            raise EvolutionError("verified_seed_recovery_ambiguous")

        if backup_present:
            backup_contract, _ = self._contract_only_snapshot(self.seed_backup_path)
            if root_present:
                if stage_present:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                root_contract = self._complete_seed_tree_contract(self.root)
                if root_contract != backup_contract:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                self._remove_recovery_tree(self.seed_backup_path)
                return

            if stage_present:
                stage_contract = self._complete_seed_tree_contract(self.seed_stage_path)
                if stage_contract != backup_contract:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
            try:
                os.replace(self.seed_backup_path, self.root)
            except OSError as exc:
                raise EvolutionError("verified_seed_recovery_failed") from exc
            if stage_present:
                self._remove_recovery_tree(self.seed_stage_path)
            return

        stage_contract = self._complete_seed_tree_contract(self.seed_stage_path)
        if root_present:
            root_contract, _ = self._contract_only_snapshot(self.root)
            if stage_contract != root_contract:
                raise EvolutionError("verified_seed_recovery_ambiguous")
        elif stage_contract is not None:
            raise EvolutionError("verified_seed_recovery_ambiguous")
        self._remove_recovery_tree(self.seed_stage_path)

    def _ensure_layout(self) -> None:
        self._require_writable()
        for path in (self.root, self.candidates_root):
            if path.exists() and path.is_symlink():
                raise EvolutionError("evolution archive directory must not be a symlink")
            path.mkdir(parents=True, exist_ok=True)
        # Candidate/source fsync chains end at ``evolution``. Sync the complete layout through the
        # workspace too, so the first creation of that root cannot be lost while later files appear
        # durable only inside an uncommitted directory entry.
        _fsync_directory_chain(
            self.candidates_root,
            self.workspace,
            error="evolution archive directory could not be persisted",
        )

    def _workspace_strategy_evidence(
        self,
    ) -> tuple[frozenset[str], frozenset[str], str | None, str | None]:
        """Read strategy evidence without creating or changing archive entries."""

        operational: set[str] = set()
        contract_strategies: set[str] = set()
        operational_error: str | None = None
        contract_error: str | None = None

        def mark_operational_invalid(error: str = _WORKSPACE_STRATEGY_INVALID) -> None:
            nonlocal operational_error
            if operational_error is None:
                operational_error = error

        def mark_contract_invalid(error: str = _WORKSPACE_STRATEGY_INVALID) -> None:
            nonlocal contract_error
            if contract_error is None:
                contract_error = error

        def observe(
            value: object,
            destination: set[str],
            mark_invalid: Callable[[], None],
        ) -> None:
            if isinstance(value, str) and value in EVOLUTION_STRATEGIES:
                destination.add(value)
            else:
                mark_invalid()

        if self._path_present(self.state_path):
            try:
                state = _strict_json_loads(
                    _read_bounded_regular_file(
                        self.state_path,
                        MAX_STATE_BYTES,
                        error=_WORKSPACE_STRATEGY_INVALID,
                    ).decode("utf-8")
                )
                if not isinstance(state, dict):
                    raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
                if "strategy" not in state:
                    mark_operational_invalid()
                else:
                    observe(state["strategy"], operational, mark_operational_invalid)
                if "config" in state:
                    config = state["config"]
                    if not isinstance(config, dict) or "strategy" not in config:
                        mark_operational_invalid()
                    else:
                        observe(config["strategy"], operational, mark_operational_invalid)
            except (
                EvolutionError,
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                mark_operational_invalid()

        contract_path = self.root / "contract.json"
        if self._path_present(contract_path):
            try:
                contract_content = _read_bounded_regular_file(
                    contract_path,
                    MAX_SOURCE_BYTES,
                    error="verified_seed_contract_invalid",
                )
                contract_payload = _strict_json_loads(contract_content.decode("utf-8"))
                if isinstance(contract_payload, dict):
                    raw_evolution = contract_payload.get("evolution")
                    if isinstance(raw_evolution, dict) and "strategy" in raw_evolution:
                        observe(
                            raw_evolution["strategy"],
                            contract_strategies,
                            mark_contract_invalid,
                        )
                contract = AlgorithmProblemContract.from_dict(contract_payload)
                observe(
                    contract.evolution.strategy,
                    contract_strategies,
                    mark_contract_invalid,
                )
            except EvolutionError as exc:
                mark_contract_invalid(str(exc))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                mark_contract_invalid()

        result_path = self.root / "result.json"
        if self._path_present(result_path):
            try:
                result_content = _read_bounded_regular_file(
                    result_path,
                    MAX_STATE_BYTES,
                    error=_WORKSPACE_STRATEGY_INVALID,
                )
                result_payload = _strict_json_loads(result_content.decode("utf-8"))
                if isinstance(result_payload, dict) and "strategy" in result_payload:
                    observe(
                        result_payload["strategy"],
                        operational,
                        mark_operational_invalid,
                    )
                expected_fields = {
                    "strategy",
                    "status",
                    "iterations",
                    "evaluated_candidates",
                    "valid_candidates",
                    "best_candidate_id",
                    "best_score",
                    "best_candidate_path",
                    "archive_path",
                    "error",
                }
                if not isinstance(result_payload, dict) or set(result_payload) != expected_fields:
                    mark_operational_invalid()
                else:
                    result = StrategyResult(**result_payload)
                    canonical = (
                        json.dumps(
                            result.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                            allow_nan=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                    if (
                        result_payload != result.to_dict()
                        or result_content != canonical
                        or result.status
                        not in {"running", "completed", "stagnated", "cancelled", "failed"}
                        or any(
                            isinstance(value, bool)
                            or not isinstance(value, int)
                            or value < 0
                            for value in (
                                result.iterations,
                                result.evaluated_candidates,
                                result.valid_candidates,
                            )
                        )
                        or result.valid_candidates > result.evaluated_candidates
                        or (
                            result.best_score is not None
                            and (
                                isinstance(result.best_score, bool)
                                or not isinstance(result.best_score, (int, float))
                                or not math.isfinite(float(result.best_score))
                            )
                        )
                        or (result.error is not None and not isinstance(result.error, str))
                    ):
                        mark_operational_invalid()
                    if result.best_candidate_id is not None:
                        _safe_id(result.best_candidate_id, "best candidate id")
                    if result.best_candidate_path is not None:
                        _safe_relative_path(result.best_candidate_path, "best candidate path")
                    _safe_relative_path(result.archive_path, "result archive path")
            except (
                EvolutionError,
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                mark_operational_invalid()

        if self._path_present(self.archive_path):
            try:
                archive_content = _read_bounded_regular_file(
                    self.archive_path,
                    MAX_ARCHIVE_BYTES,
                    error="evolution archive is invalid or exceeds the bounded size",
                ).decode("utf-8")
                for line in archive_content.splitlines():
                    if not line.strip():
                        continue
                    payload = _strict_json_loads(line)
                    if not isinstance(payload, dict) or "strategy" not in payload:
                        mark_operational_invalid()
                        continue
                    observe(
                        payload["strategy"],
                        operational,
                        mark_operational_invalid,
                    )
                # Preserve the reader's complete structural checks while translating malformed
                # strategy evidence into one stable fail-closed writer error below.
                self.records()
            except EvolutionError as exc:
                # Keep the ordinary-integrity reader's stable diagnosis when strategy parsing
                # itself succeeded. Duplicate/non-finite strategy evidence is rejected earlier
                # by the strict decoder and remains the generic workspace-strategy error.
                mark_operational_invalid(str(exc))
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                mark_operational_invalid()

        if self._path_present(self.offspring_outcomes_path):
            try:
                outcomes_content = _read_bounded_regular_file(
                    self.offspring_outcomes_path,
                    MAX_ARCHIVE_BYTES,
                    error=_WORKSPACE_STRATEGY_INVALID,
                ).decode("utf-8")
                for line in outcomes_content.splitlines():
                    if not line.strip():
                        continue
                    if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                        raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
                    _strict_json_loads(line)
                self.offspring_outcomes()
                operational.add("population")
            except (
                EvolutionError,
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                mark_operational_invalid()

        return (
            frozenset(operational),
            frozenset(contract_strategies),
            operational_error,
            contract_error,
        )

    def _guard_active_write(self, strategy: object = _MISSING_STRATEGY) -> str | None:
        """Reject retired, malformed, or cross-strategy workspaces before mutation."""

        self._guard_producer_publication_recovery()

        if strategy is not _MISSING_STRATEGY:
            if strategy == "loop":
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            if not isinstance(strategy, str) or strategy not in ACTIVE_EVOLUTION_STRATEGIES:
                raise EvolutionError("unsupported candidate strategy")

        operational, contract_strategies, operational_error, contract_error = (
            self._workspace_strategy_evidence()
        )
        if "loop" in operational or "loop" in contract_strategies:
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if (
            operational_error is not None
            or contract_error is not None
            or len(operational) > 1
            or len(contract_strategies) > 1
        ):
            raise EvolutionError(
                operational_error or contract_error or _WORKSPACE_STRATEGY_INVALID
            )
        if (
            strategy is not _MISSING_STRATEGY
            and operational
            and strategy not in operational
        ):
            raise EvolutionError(_WORKSPACE_STRATEGY_MISMATCH)
        if operational:
            return next(iter(operational))
        active_contract = contract_strategies.intersection(ACTIVE_EVOLUTION_STRATEGIES)
        if strategy is _MISSING_STRATEGY and len(active_contract) == 1:
            return next(iter(active_contract))
        return strategy if isinstance(strategy, str) else None

    @staticmethod
    def _guard_seed_state_strategy(
        state: object,
        canonical_strategy: object,
    ) -> None:
        """Bind a seed transaction's state tag to its canonical candidate strategy."""

        if canonical_strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if (
            not isinstance(canonical_strategy, str)
            or canonical_strategy not in ACTIVE_EVOLUTION_STRATEGIES
        ):
            raise EvolutionError("verified_seed_state_invalid")
        if not isinstance(state, dict) or "strategy" not in state:
            raise EvolutionError("verified_seed_state_invalid")
        state_strategy = state["strategy"]
        if state_strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if "config" in state:
            config = state["config"]
            if not isinstance(config, dict) or "strategy" not in config:
                raise EvolutionError("verified_seed_state_invalid")
            config_strategy = config["strategy"]
            if config_strategy == "loop":
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            if (
                not isinstance(config_strategy, str)
                or config_strategy not in ACTIVE_EVOLUTION_STRATEGIES
                or config_strategy != state_strategy
                or config_strategy != canonical_strategy
            ):
                raise EvolutionError("verified_seed_state_invalid")
        if state_strategy != canonical_strategy:
            raise EvolutionError("verified_seed_state_invalid")

    def records(self) -> list[Candidate]:
        self._guard_producer_publication_recovery()
        if not self.archive_path.exists():
            if self.archive_path.is_symlink():
                raise EvolutionError("evolution archive is invalid or exceeds the bounded size")
            return []
        if (
            self.archive_path.is_symlink()
            or not self.archive_path.is_file()
            or self.archive_path.stat().st_size > MAX_ARCHIVE_BYTES
        ):
            raise EvolutionError("evolution archive is invalid or exceeds the bounded size")
        records: list[Candidate] = []
        seen: set[str] = set()
        archive_content = _read_bounded_regular_file(
            self.archive_path,
            MAX_ARCHIVE_BYTES,
            error="evolution archive is invalid or exceeds the bounded size",
        ).decode("utf-8")
        for line in archive_content.splitlines():
            if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                raise EvolutionError("evolution archive record is too large")
            if not line.strip():
                continue
            payload = json.loads(line)
            modern_record = False
            if isinstance(payload, dict):
                integrity_fields = {"source_sha256", "receipt_sha256", "integrity"}
                if integrity_fields & set(payload):
                    modern_record = True
                    ordinary_fields = {
                        "candidate_id",
                        "code_path",
                        "parent_id",
                        "generation",
                        "iteration",
                        "strategy",
                        "island_id",
                        "evaluation",
                        "metadata",
                        "created_at",
                        *integrity_fields,
                    }
                    if "bundle_evidence" in payload:
                        ordinary_fields.add("bundle_evidence")
                    if set(payload) != ordinary_fields:
                        raise EvolutionError("ordinary_candidate_record_invalid")
            candidate = Candidate.from_dict(payload)
            if modern_record:
                try:
                    if _canonical_json_bytes(payload) != _canonical_json_bytes(
                        candidate.to_dict()
                    ):
                        raise EvolutionError("ordinary_candidate_record_invalid")
                except (TypeError, ValueError) as exc:
                    raise EvolutionError("ordinary_candidate_record_invalid") from exc
            if candidate.strategy == "population":
                has_seed_metadata = "seed_handoff" in candidate.metadata
                has_seed_id = candidate.candidate_id.startswith("seed-")
                if has_seed_metadata != has_seed_id:
                    raise EvolutionError("verified_seed_identity_mismatch")
            if candidate.candidate_id in seen:
                raise EvolutionError("evolution archive contains a duplicate candidate id")
            seen.add(candidate.candidate_id)
            records.append(candidate)
        return records

    def offspring_outcomes(self) -> tuple[OffspringOutcome, ...]:
        self._guard_producer_publication_recovery()
        path = self.offspring_outcomes_path
        if not path.exists():
            if path.is_symlink():
                raise EvolutionError("population_outcomes_invalid")
            return ()
        try:
            if path.is_symlink() or not path.is_file():
                raise EvolutionError("population_outcomes_invalid")
            if path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise EvolutionError("population_outcomes_invalid")
            outcomes: list[OffspringOutcome] = []
            seen: set[tuple[int, int]] = set()
            content = _read_bounded_regular_file(
                path,
                MAX_ARCHIVE_BYTES,
                error="population_outcomes_invalid",
            ).decode("utf-8")
            for line in content.splitlines():
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                    raise EvolutionError("population_outcomes_invalid")
                outcome = OffspringOutcome.from_dict(json.loads(line))
                key = (outcome.iteration, outcome.attempt)
                if key in seen:
                    raise EvolutionError("population_outcomes_invalid")
                seen.add(key)
                outcomes.append(outcome)
            return tuple(outcomes)
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("population_outcomes_invalid") from exc

    def append_offspring_outcome(self, outcome: OffspringOutcome) -> None:
        self._require_writable()
        if not isinstance(outcome, OffspringOutcome):
            raise TypeError("outcome must be an OffspringOutcome")
        self._guard_active_write("population")
        self._ensure_layout()
        if any(
            item.iteration == outcome.iteration and item.attempt == outcome.attempt
            for item in self.offspring_outcomes()
        ):
            raise EvolutionError("population_outcome_duplicate")
        line = json.dumps(
            outcome.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("population_outcomes_invalid")
        descriptor: int | None = None
        root_descriptor: int | None = None
        append_started = False
        pre_append_size = 0
        try:
            root_descriptor = os.open(
                self.root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            descriptor = os.open(
                self.offspring_outcomes_path.name,
                os.O_WRONLY
                | os.O_APPEND
                | os.O_CREAT
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise EvolutionError("population_outcomes_invalid")
            pre_append_size = before.st_size
            encoded_line = (line + "\n").encode("utf-8")
            if pre_append_size + len(encoded_line) > MAX_ARCHIVE_BYTES:
                raise EvolutionError("population_outcomes_invalid")
            append_started = True
            view = memoryview(encoded_line)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("outcome append made no progress")
                written += count
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            current = os.stat(
                self.offspring_outcomes_path.name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_nlink != 1
                or after.st_size != pre_append_size + len(encoded_line)
                or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise OSError("outcome publication identity changed")
            os.fsync(root_descriptor)
        except EvolutionError:
            raise
        except OSError as exc:
            if descriptor is not None and append_started:
                try:
                    if root_descriptor is None:
                        raise OSError("outcome append root descriptor is unavailable")
                    _rollback_appended_regular_file(
                        descriptor,
                        root_descriptor,
                        self.offspring_outcomes_path.name,
                        pre_append_size,
                    )
                except OSError as rollback_exc:
                    raise EvolutionError("population_outcome_publication_unknown") from rollback_exc
            raise EvolutionError("population_outcome_persist_failed") from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if root_descriptor is not None:
                try:
                    os.close(root_descriptor)
                except OSError:
                    pass

    def next_id(self) -> str:
        self._guard_producer_publication_recovery()
        numbers = []
        for candidate in self.records():
            match = re.fullmatch(r"candidate-(\d+)", candidate.candidate_id)
            if match:
                numbers.append(int(match.group(1)))
        return f"candidate-{(max(numbers, default=0) + 1):04d}"

    def candidate_source_path(self, candidate_id: str, filename: str) -> Path:
        self._guard_producer_publication_recovery()
        _safe_id(candidate_id, "candidate_id")
        relative = _safe_relative_path(filename, "candidate filename")
        if Path(relative).name in _RESERVED_CANDIDATE_SOURCE_BASENAMES:
            # Sidecars and their deterministic private temporary names live beside the source.
            # Reserving those basenames prevents source/evidence aliasing and partial commits.
            raise EvolutionError("candidate filename is reserved for integrity evidence")
        if self.archive_path.exists() and self.archive_path.is_symlink():
            raise EvolutionError("evolution archive must not be a symlink")
        candidate_dir = self.candidates_root / candidate_id
        _reject_symlink_components(candidate_dir, self.candidates_root, "candidate path")
        raw_result = candidate_dir / relative
        # Check the lexical path before resolving it.  Resolving first would turn a malicious
        # source symlink into an apparently safe regular path and could redirect a write outside
        # the candidate directory.
        _reject_symlink_components(raw_result, self.candidates_root, "candidate path")
        if raw_result.is_symlink():
            raise EvolutionError("candidate path must not contain a symlink")
        result = _confined(self.workspace, raw_result, "candidate path")
        try:
            result.relative_to(candidate_dir.resolve(strict=False))
        except ValueError as exc:
            raise EvolutionError("candidate path escapes candidate directory") from exc
        record_path = raw_result.parent / ORDINARY_RECORD_FILENAME
        if record_path.is_symlink():
            raise EvolutionError("candidate record must not be a symlink")
        return result

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes, *, error: str) -> None:
        """Write one private file and publish it with a same-directory replace."""

        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise EvolutionError(error)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise EvolutionError(error)
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                # O_EXCL prevents a pre-planted hardlink from being opened; O_NOFOLLOW also
                # documents and enforces the no-link contract on platforms that provide it.
                0o600,
            )
            try:
                view = memoryview(content)
                written = 0
                while written < len(view):
                    count = os.write(descriptor, view[written:])
                    if count <= 0:
                        raise OSError("private write made no progress")
                    written += count
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
            _fsync_directory(path.parent, error=error)
        except OSError as exc:
            try:
                if temporary.exists() and not temporary.is_symlink():
                    temporary.unlink()
            except OSError:
                pass
            raise EvolutionError(error) from exc

    def candidate_receipt_path(
        self,
        candidate_id: str,
        source_path: str | Path | None = None,
    ) -> Path:
        """Return the receipt sidecar path for a candidate source.

        The historical one-argument form resolves to ``candidates/<id>/receipt.json``.  Ordinary
        candidates may use a nested source filename, in which case persistence places sidecars
        beside that source (for example ``src/main.py`` -> ``src/receipt.json``).  Accepting an
        optional source path keeps the public form compatible while allowing resume validation to
        address nested candidates without guessing or following links.
        """
        _safe_id(candidate_id, "candidate_id")
        candidate_dir = self.candidates_root / candidate_id
        _reject_symlink_components(candidate_dir, self.candidates_root, "candidate receipt path")
        if source_path is None:
            raw_result = candidate_dir / ORDINARY_RECEIPT_FILENAME
        else:
            raw_source = Path(source_path).expanduser()
            if not raw_source.is_absolute():
                raw_source = self.workspace / raw_source
            _reject_symlink_components(raw_source, self.candidates_root, "candidate receipt path")
            try:
                source = _confined(self.workspace, raw_source, "candidate receipt path")
                source.relative_to(candidate_dir.resolve(strict=False))
            except ValueError as exc:
                raise EvolutionError("candidate receipt path escapes candidate directory") from exc
            raw_result = source.parent / ORDINARY_RECEIPT_FILENAME
        _reject_symlink_components(raw_result, self.candidates_root, "candidate receipt path")
        if raw_result.is_symlink():
            raise EvolutionError("candidate receipt must not be a symlink")
        result = _confined(self.workspace, raw_result, "candidate receipt path")
        try:
            result.relative_to(candidate_dir.resolve(strict=False))
        except ValueError as exc:
            raise EvolutionError("candidate receipt path escapes candidate directory") from exc
        return result

    def _candidate_execution_sha256(
        self,
        source_path: Path,
        *,
        expected_sha256: str | None = None,
    ) -> str | None:
        """Return a bounded regular execution-evidence digest beside ``source_path``.

        A missing file is valid only when no digest was claimed.  If a file is present, callers
        always receive its digest so persistence can bind it and resume can reject an unbound file.
        The checks happen before reading bytes to avoid following symlinks or blocking on special
        files supplied at the evaluator boundary.
        """

        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256)
        ):
            raise EvolutionError("ordinary_candidate_execution_mismatch")
        snapshot = self._candidate_execution_snapshot(source_path)
        if snapshot is None:
            if expected_sha256 is not None:
                raise EvolutionError("ordinary_candidate_execution_mismatch")
            return None
        try:
            snapshot.validate(snapshot.content)
            digest = hashlib.sha256(snapshot.content).hexdigest()
            if expected_sha256 is not None and digest != expected_sha256:
                raise EvolutionError("ordinary_candidate_execution_mismatch")
            return digest
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError("ordinary_candidate_execution_mismatch") from exc
        finally:
            snapshot.close()

    def _candidate_execution_snapshot(
        self,
        source_path: Path,
    ) -> _HeldRegularFileSnapshot | None:
        """Open optional execution evidence without following links or losing file identity."""

        raw_path = source_path.parent / ORDINARY_EXECUTION_FILENAME
        present = raw_path.exists() or raw_path.is_symlink()
        if not present:
            return None
        try:
            _reject_symlink_components(
                raw_path,
                self.candidates_root,
                "ordinary candidate execution path",
            )
            if raw_path.is_symlink() or not raw_path.is_file():
                raise EvolutionError("ordinary_candidate_execution_mismatch")
            path = _confined(
                self.workspace,
                raw_path,
                "ordinary candidate execution path",
            )
            return _HeldRegularFileSnapshot.open(
                path,
                MAX_ARCHIVE_LINE_BYTES,
                error="ordinary_candidate_execution_mismatch",
            )
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError("ordinary_candidate_execution_mismatch") from exc

    def _default_candidate_authority(self) -> CandidateIntegrityAuthority:
        state = self.read_state()
        existing = state.get("candidate_integrity_authority")
        if existing is not None:
            return CandidateIntegrityAuthority.from_dict(existing)
        contract_sha256 = state.get("contract_sha256")
        if not isinstance(contract_sha256, str) or not _SHA256.fullmatch(contract_sha256):
            contract_sha256 = _protocol_identity("lunar-unknown-contract-v1")
        return CandidateIntegrityAuthority(
            schema_version=CANDIDATE_INTEGRITY_SCHEMA_VERSION,
            contract_sha256=contract_sha256,
            evaluator_kind="native",
            evaluator_fingerprint=_native_evaluator_identity(),
            dependency_sha256=_native_dependency_identity(),
            environment_sha256=_native_environment_identity(),
            runner_fingerprint=_native_runner_identity(),
            generator_fingerprint=_native_generator_identity(),
        )

    def _candidate_archive_digest(self, records: Sequence[Candidate] | None = None) -> str:
        if records is None:
            records = self.records()
        records = tuple(candidate for candidate in records if not self._is_seed_candidate(candidate))
        # ``records()`` preserves the append order of archive.jsonl.  The Feature 087 state
        # digest binds that order so rearranging otherwise valid records cannot produce the same
        # ordinary archive identity.  Keep PopulationStrategy._candidate_digest unchanged: it is
        # part of the older offspring-outcome schema and deliberately canonicalizes by ID.
        return _canonical_sha256([candidate.to_dict() for candidate in records])

    @staticmethod
    def _is_seed_candidate(candidate: Candidate) -> bool:
        # The ``seed-`` prefix is an identity convention, not proof of admission.  Trusting it
        # alone would let a forged ordinary population record bypass receipt validation simply by
        # choosing a seed-looking ID.  A committed seed always carries the validated handoff
        # metadata; a missing/tampered marker therefore falls into the ordinary fail-closed path.
        return "seed_handoff" in candidate.metadata

    def read_candidate_receipt(
        self,
        candidate_id: str,
        source_path: str | Path | None = None,
    ) -> CandidateReceipt:
        self._guard_producer_publication_recovery()
        if source_path is None:
            # Preserve the original root-sidecar lookup for callers that do not have an archive
            # record yet.  Once a candidate is published, derive the sidecar location from its
            # recorded source path so nested filenames are handled correctly.
            try:
                matches = [
                    item for item in self.records() if item.candidate_id == candidate_id
                ]
            except (EvolutionError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                matches = []
            if len(matches) == 1:
                source_path = self.workspace / matches[0].code_path
        path = self.candidate_receipt_path(candidate_id, source_path)
        if not path.exists() or path.is_symlink() or not path.is_file():
            raise EvolutionError("ordinary_candidate_receipt_missing")
        if path.stat().st_size > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("ordinary_candidate_receipt_invalid")
        try:
            payload = json.loads(
                _read_bounded_regular_file(
                    path,
                    MAX_ARCHIVE_LINE_BYTES,
                    error="ordinary_candidate_receipt_invalid",
                ).decode("utf-8")
            )
            return CandidateReceipt.from_dict(payload)
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("ordinary_candidate_receipt_invalid") from exc

    def validate_candidate_integrity(
        self,
        *,
        authority: CandidateIntegrityAuthority | Mapping[str, Any] | None = None,
        require_all: bool = True,
        allowed_delayed_root_ids: Iterable[str] = (),
        records: Sequence[Candidate] | None = None,
    ) -> tuple[Candidate, ...]:
        """Validate all ordinary candidate sidecars and source/record bindings.

        Imported seed candidates are intentionally delegated to their existing verified-seed gate.
        ``require_all=False`` is useful for read-only inspection of a mixed historical archive.
        """

        self._guard_producer_publication_recovery()
        if records is None:
            validated_records = tuple(self.records())
        else:
            validated_records = tuple(records)
            if any(not isinstance(candidate, Candidate) for candidate in validated_records):
                raise EvolutionError("ordinary_candidate_integrity_mismatch")
        ordinary = [
            candidate
            for candidate in validated_records
            if candidate.strategy == "population" and not self._is_seed_candidate(candidate)
        ]
        if not ordinary:
            return validated_records
        _validate_bundle_attempt_ownership(
            (candidate.candidate_id, candidate.bundle_evidence) for candidate in ordinary
        )
        if authority is None:
            expected = self._default_candidate_authority()
        elif isinstance(authority, CandidateIntegrityAuthority):
            expected = authority
        else:
            expected = CandidateIntegrityAuthority.from_dict(dict(authority))
        try:
            delayed_roots = frozenset(allowed_delayed_root_ids)
        except TypeError as exc:
            raise EvolutionError("ordinary_candidate_lineage_mismatch") from exc
        if any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item) for item in delayed_roots):
            raise EvolutionError("ordinary_candidate_lineage_mismatch")
        seen_by_id: dict[str, Candidate] = {}
        for candidate in validated_records:
            is_ordinary = (
                candidate.strategy == "population" and not self._is_seed_candidate(candidate)
            )
            if not is_ordinary:
                seen_by_id[candidate.candidate_id] = candidate
                continue
            if (
                candidate.source_sha256 is None
                or candidate.receipt_sha256 is None
                or candidate.integrity is None
            ):
                if require_all:
                    raise EvolutionError(LEGACY_CANDIDATE_INTEGRITY_ERROR)
                seen_by_id[candidate.candidate_id] = candidate
                continue
            # Ordinary population lineage is part of the receipt authority.  Keep the checks
            # independent from the source/receipt bytes so a caller cannot rewrite every durable
            # projection around a non-existent or cross-strategy parent and make it look valid.
            if candidate.strategy != "population" or candidate.island_id is None:
                raise EvolutionError("ordinary_candidate_lineage_mismatch")
            parent_id = candidate.parent_id
            if parent_id is None:
                if candidate.generation != 0 or (
                    candidate.iteration != 0
                    and candidate.candidate_id not in delayed_roots
                ):
                    raise EvolutionError("ordinary_candidate_lineage_mismatch")
            else:
                # Parentage is causal: an append-only child may reference only a population
                # candidate already published earlier in the archive.
                parent = seen_by_id.get(parent_id)
                if (
                    parent is None
                    or parent.strategy != "population"
                    or parent.evaluation.validity != 1
                    or parent.candidate_id == candidate.candidate_id
                    or candidate.generation != parent.generation + 1
                    or candidate.iteration <= parent.iteration
                ):
                    raise EvolutionError("ordinary_candidate_lineage_mismatch")
            try:
                candidate_root = self.candidates_root / candidate.candidate_id
                raw_source_path = self.workspace / candidate.code_path
                try:
                    raw_source_path.relative_to(candidate_root)
                except ValueError as exc:
                    raise EvolutionError("ordinary_candidate_source_invalid") from exc
                _reject_symlink_components(
                    raw_source_path,
                    self.candidates_root,
                    "ordinary candidate source path",
                )
                if raw_source_path.is_symlink() or not raw_source_path.is_file():
                    raise EvolutionError("ordinary_candidate_source_invalid")
                source_path = _confined(
                    self.workspace,
                    raw_source_path,
                    "ordinary candidate source path",
                )
                if source_path.is_symlink() or not source_path.is_file():
                    raise EvolutionError("ordinary_candidate_source_invalid")
                source_bytes = _read_bounded_regular_file(
                    source_path,
                    MAX_SOURCE_BYTES,
                    error="ordinary_candidate_source_mismatch",
                )
                source_digest = hashlib.sha256(source_bytes).hexdigest()
                if source_digest != candidate.source_sha256:
                    raise EvolutionError("ordinary_candidate_source_mismatch")
                receipt = self.read_candidate_receipt(
                    candidate.candidate_id,
                    source_path=source_path,
                )
                if receipt.receipt_sha256 != candidate.receipt_sha256:
                    raise EvolutionError("ordinary_candidate_receipt_mismatch")
                if (
                    receipt.candidate_id != candidate.candidate_id
                    or receipt.source_sha256 != source_digest
                    or receipt.contract_sha256 != expected.contract_sha256
                    or receipt.evaluator_kind != expected.evaluator_kind
                    or receipt.evaluator_fingerprint != expected.evaluator_fingerprint
                    or receipt.dependency_sha256 != expected.dependency_sha256
                    or receipt.environment_sha256 != expected.environment_sha256
                    or receipt.runner_fingerprint != expected.runner_fingerprint
                    or receipt.generator_fingerprint != expected.generator_fingerprint
                    or receipt.parent_id != candidate.parent_id
                    or receipt.generation != candidate.generation
                    or receipt.iteration != candidate.iteration
                    or receipt.island_id != candidate.island_id
                    or _canonical_json_bytes(receipt.evaluation_report().to_dict())
                    != _canonical_json_bytes(candidate.evaluation.to_dict())
                    or _canonical_json_bytes(receipt.bundle_evidence)
                    != _canonical_json_bytes(candidate.bundle_evidence)
                ):
                    raise EvolutionError("ordinary_candidate_integrity_mismatch")
                integrity = candidate.integrity
                expected_projection = {
                    **expected.to_dict(),
                    "candidate_id": candidate.candidate_id,
                    "parent_id": candidate.parent_id,
                    "generation": candidate.generation,
                    "iteration": candidate.iteration,
                    "island_id": candidate.island_id,
                    "receipt_sha256": receipt.receipt_sha256,
                    "source_sha256": source_digest,
                }
                if candidate.bundle_evidence is not None:
                    from .bundle_evolution import validate_candidate_bundle_evidence

                    expected_projection["bundle_evidence_sha256"] = _canonical_sha256(candidate.bundle_evidence)
                    validate_candidate_bundle_evidence(
                        self.workspace,
                        candidate.bundle_evidence,
                        code_path=candidate.code_path,
                        evaluation=candidate.evaluation,
                        authority=expected,
                    )
                if _canonical_json_bytes(integrity) != _canonical_json_bytes(
                    expected_projection
                ):
                    raise EvolutionError("ordinary_candidate_integrity_mismatch")
                raw_record_path = raw_source_path.parent / ORDINARY_RECORD_FILENAME
                _reject_symlink_components(
                    raw_record_path,
                    self.candidates_root,
                    "ordinary candidate record path",
                )
                if raw_record_path.is_symlink() or not raw_record_path.is_file():
                    raise EvolutionError("ordinary_candidate_record_missing")
                record_path = _confined(
                    self.workspace,
                    raw_record_path,
                    "ordinary candidate record path",
                )
                if record_path.stat().st_size > MAX_ARCHIVE_LINE_BYTES:
                    raise EvolutionError("ordinary_candidate_record_invalid")
                record_payload = json.loads(
                    _read_bounded_regular_file(
                        record_path,
                        MAX_ARCHIVE_LINE_BYTES,
                        error="ordinary_candidate_record_invalid",
                    ).decode("utf-8")
                )
                if _canonical_json_bytes(record_payload) != _canonical_json_bytes(
                    candidate.to_dict()
                ):
                    raise EvolutionError("ordinary_candidate_record_mismatch")
                execution_sha256 = self._candidate_execution_sha256(
                    source_path,
                    expected_sha256=receipt.execution_sha256,
                )
                if execution_sha256 != receipt.execution_sha256:
                    raise EvolutionError("ordinary_candidate_execution_mismatch")
            except EvolutionError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise EvolutionError("ordinary_candidate_integrity_mismatch") from exc
            seen_by_id[candidate.candidate_id] = candidate
        return validated_records

    def persist(
        self,
        draft: CandidateDraft,
        *,
        candidate_id: str | None = None,
        strategy: Literal["population", "openevolve"],
        iteration: int,
        generation: int,
        parent_id: str | None = None,
        island_id: int | None = None,
        evaluation: EvaluationReport,
        integrity_authority: CandidateIntegrityAuthority | Mapping[str, Any] | None = None,
        execution_sha256: str | None = None,
        source_snapshot: _HeldRegularFileSnapshot | None = None,
        execution_snapshot: _HeldRegularFileSnapshot | None = None,
        bundle_evidence: dict[str, Any] | None = None,
    ) -> Candidate:
        self._require_writable()
        self._guard_active_write(strategy)
        if strategy == "openevolve":
            raise EvolutionError("openevolve_candidate_requires_verified_seed_commit")
        if draft.source_files is not None and bundle_evidence is None:
            raise EvolutionError("bundle_candidate_evidence_required")
        if candidate_id is not None:
            _safe_id(candidate_id, "candidate_id")
            if strategy == "population" and candidate_id.startswith("seed-"):
                raise EvolutionError("ordinary_candidate_seed_identity_reserved")
        self._ensure_layout()
        existing_records = self.records()
        candidate_id = candidate_id or self.next_id()
        if any(item.candidate_id == candidate_id for item in existing_records):
            raise EvolutionError(f"candidate id already exists: {candidate_id}")
        path = self.candidate_source_path(candidate_id, draft.filename)
        if path.parent.exists() and any(
            (path.parent / name).exists() or (path.parent / name).is_symlink()
            for name in (ORDINARY_RECORD_FILENAME, ORDINARY_RECEIPT_FILENAME)
        ):
            # Execution-aware evaluators may legitimately create execution.json, data/raw, and
            # output artifacts beside the source.  A pre-existing record/receipt, however, means
            # this candidate directory was already published or partially committed.
            raise EvolutionError("ordinary_candidate_staging_conflict")
        source_bytes = draft.source.encode("utf-8")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        normalized_evaluation = _sanitized_evaluation(evaluation)
        if bundle_evidence is not None:
            from .bundle_evolution import validate_bundle_evidence_shape

            bundle_evidence = validate_bundle_evidence_shape(bundle_evidence)
        _validate_bundle_attempt_ownership([
            *((candidate.candidate_id, candidate.bundle_evidence) for candidate in existing_records),
            (candidate_id, bundle_evidence),
        ])
        if strategy == "population":
            if integrity_authority is None:
                authority = self._default_candidate_authority()
            elif isinstance(integrity_authority, CandidateIntegrityAuthority):
                authority = integrity_authority
            else:
                authority = CandidateIntegrityAuthority.from_dict(dict(integrity_authority))
            if draft.source_files is not None:
                from .bundle_evolution import validate_bundle_draft

                if validate_bundle_draft(draft, authority.contract_sha256).digest() != bundle_evidence["bundle_sha256"]:
                    raise EvolutionError("bundle_candidate_source_mismatch")
            state = self.read_state()
            marker_names = {
                "candidate_integrity_schema_version",
                "candidate_integrity_authority",
                "candidate_archive_sha256",
            }
            present_markers = marker_names.intersection(state)
            if present_markers and present_markers != marker_names:
                raise EvolutionError("ordinary_candidate_integrity_state_invalid")
            if present_markers:
                if (
                    state.get("candidate_integrity_schema_version")
                    != CANDIDATE_INTEGRITY_SCHEMA_VERSION
                ):
                    raise EvolutionError("ordinary_candidate_integrity_state_invalid")
                try:
                    state_authority = CandidateIntegrityAuthority.from_dict(
                        state["candidate_integrity_authority"]
                    )
                except (TypeError, ValueError, EvolutionError) as exc:
                    raise EvolutionError("ordinary_candidate_integrity_state_invalid") from exc
                if state_authority.to_dict() != authority.to_dict():
                    raise EvolutionError("ordinary_candidate_integrity_authority_mismatch")
            if authority.contract_sha256 != state.get(
                "contract_sha256", authority.contract_sha256
            ):
                raise EvolutionError("ordinary_candidate_integrity_mismatch")
            authority_fields = set(authority.to_dict())
            for existing_candidate in existing_records:
                if existing_candidate.strategy != "population" or self._is_seed_candidate(
                    existing_candidate
                ):
                    continue
                projection = existing_candidate.integrity
                if not isinstance(projection, dict) or not authority_fields <= set(projection):
                    raise EvolutionError(LEGACY_CANDIDATE_INTEGRITY_ERROR)
                try:
                    archived_authority = CandidateIntegrityAuthority.from_dict(
                        {name: projection[name] for name in authority_fields}
                    )
                    archived_receipt = self.read_candidate_receipt(
                        existing_candidate.candidate_id,
                        source_path=self.workspace / existing_candidate.code_path,
                    )
                except (KeyError, TypeError, ValueError, EvolutionError) as exc:
                    raise EvolutionError("ordinary_candidate_integrity_mismatch") from exc
                if archived_authority.to_dict() != authority.to_dict() or any(
                    getattr(archived_receipt, name) != getattr(authority, name)
                    for name in authority_fields - {"schema_version"}
                ):
                    raise EvolutionError("ordinary_candidate_integrity_authority_mismatch")
            metadata = _validate_ordinary_metadata(draft.metadata)
            if execution_snapshot is None:
                execution_sha256 = self._candidate_execution_sha256(
                    path,
                    expected_sha256=execution_sha256,
                )
            else:
                expected_execution_path = path.parent / ORDINARY_EXECUTION_FILENAME
                if execution_snapshot.path != expected_execution_path:
                    raise EvolutionError("ordinary_candidate_execution_mismatch")
                execution_snapshot.validate(execution_snapshot.content)
                observed_execution_sha256 = hashlib.sha256(
                    execution_snapshot.content
                ).hexdigest()
                if (
                    execution_sha256 is not None
                    and execution_sha256 != observed_execution_sha256
                ):
                    raise EvolutionError("ordinary_candidate_execution_mismatch")
                execution_sha256 = observed_execution_sha256
            receipt = CandidateReceipt.from_report(
                normalized_evaluation,
                candidate_id=candidate_id,
                source_sha256=source_sha256,
                contract_sha256=authority.contract_sha256,
                evaluator_kind=authority.evaluator_kind,
                evaluator_fingerprint=authority.evaluator_fingerprint,
                dependency_sha256=authority.dependency_sha256,
                environment_sha256=authority.environment_sha256,
                runner_fingerprint=authority.runner_fingerprint,
                generator_fingerprint=authority.generator_fingerprint,
                parent_id=parent_id,
                generation=generation,
                iteration=iteration,
                island_id=island_id,
                execution_sha256=execution_sha256,
                bundle_evidence=bundle_evidence,
            )
            projection = {
                **authority.to_dict(),
                "candidate_id": candidate_id,
                "parent_id": parent_id,
                "generation": generation,
                "iteration": iteration,
                "island_id": island_id,
                "receipt_sha256": receipt.receipt_sha256,
                "source_sha256": source_sha256,
            }
            if bundle_evidence is not None:
                projection["bundle_evidence_sha256"] = _canonical_sha256(bundle_evidence)
            candidate = Candidate(
                candidate_id=candidate_id,
                code_path=path.relative_to(self.workspace).as_posix(),
                parent_id=parent_id,
                generation=generation,
                iteration=iteration,
                strategy=strategy,
                island_id=island_id,
                evaluation=normalized_evaluation,
                metadata=metadata,
                source_sha256=source_sha256,
                receipt_sha256=receipt.receipt_sha256,
                integrity=projection,
                bundle_evidence=bundle_evidence,
            )
            receipt_text = json.dumps(
                receipt.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ) + "\n"
            if len(receipt_text.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                raise EvolutionError("ordinary_candidate_receipt_too_large")
        else:
            candidate = Candidate(
                candidate_id=candidate_id,
                code_path=path.relative_to(self.workspace).as_posix(),
                parent_id=parent_id,
                generation=generation,
                iteration=iteration,
                strategy=strategy,
                island_id=island_id,
                evaluation=normalized_evaluation,
                metadata=draft.metadata,
            )
            receipt_text = None
        line = json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("candidate record exceeds the bounded archive record size")
        if path.exists() or path.is_symlink():
            _reject_symlink_components(path, self.candidates_root, "candidate path")
            if path.is_symlink() or not path.is_file():
                raise EvolutionError("ordinary_candidate_source_persist_failed")
            staged_source = _read_bounded_regular_file(
                path,
                MAX_SOURCE_BYTES,
                error="ordinary_candidate_source_persist_failed",
            )
            if staged_source != source_bytes:
                raise EvolutionError("ordinary_candidate_source_changed")
        else:
            self._atomic_write_bytes(
                path,
                source_bytes,
                error="ordinary_candidate_source_persist_failed",
            )

        def validate_publication_inputs() -> None:
            if source_snapshot is None:
                current_source = _read_bounded_regular_file(
                    path,
                    MAX_SOURCE_BYTES,
                    error="ordinary_candidate_source_changed",
                )
                if current_source != source_bytes:
                    raise EvolutionError("ordinary_candidate_source_changed")
            else:
                if source_snapshot.path != path:
                    raise EvolutionError("ordinary_candidate_source_changed")
                source_snapshot.validate(source_bytes)
            if strategy != "population":
                return
            if execution_snapshot is None:
                observed_execution = self._candidate_execution_sha256(path)
            else:
                if execution_snapshot.path != path.parent / ORDINARY_EXECUTION_FILENAME:
                    raise EvolutionError("ordinary_candidate_execution_mismatch")
                execution_snapshot.validate(execution_snapshot.content)
                observed_execution = hashlib.sha256(execution_snapshot.content).hexdigest()
            if observed_execution != execution_sha256:
                raise EvolutionError("ordinary_candidate_execution_mismatch")
            if bundle_evidence is not None:
                from .bundle_evolution import validate_candidate_bundle_evidence

                validate_candidate_bundle_evidence(
                    self.workspace,
                    bundle_evidence,
                    code_path=candidate.code_path,
                    evaluation=normalized_evaluation,
                    authority=authority,
                )

        validate_publication_inputs()
        record_path = path.parent / ORDINARY_RECORD_FILENAME
        if self.archive_path.exists() and self.archive_path.is_symlink():
            raise EvolutionError("evolution archive must not be a symlink")
        if record_path.exists() and record_path.is_symlink():
            raise EvolutionError("candidate record must not be a symlink")
        if receipt_text is not None:
            self._atomic_write_bytes(
                path.parent / ORDINARY_RECEIPT_FILENAME,
                receipt_text.encode("utf-8"),
                error="ordinary_candidate_receipt_persist_failed",
            )
            validate_publication_inputs()
        self._atomic_write_bytes(
            record_path,
            (line + "\n").encode("utf-8"),
            error="ordinary_candidate_record_persist_failed",
        )
        validate_publication_inputs()
        _fsync_directory_chain(
            path.parent,
            self.root,
            error="ordinary_candidate_sidecar_persist_failed",
        )
        validate_publication_inputs()
        descriptor: int | None = None
        root_descriptor: int | None = None
        append_started = False
        pre_append_size = 0
        try:
            if self.archive_path.is_symlink() or (
                self.archive_path.exists() and not self.archive_path.is_file()
            ):
                raise EvolutionError("evolution archive must not be a symlink")
            root_descriptor = os.open(
                self.root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            descriptor = os.open(
                self.archive_path.name,
                os.O_WRONLY
                | os.O_APPEND
                | os.O_CREAT
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise EvolutionError("evolution archive must be a private regular file")
            pre_append_size = before.st_size
            encoded_line = (line + "\n").encode("utf-8")
            if pre_append_size + len(encoded_line) > MAX_ARCHIVE_BYTES:
                raise EvolutionError(
                    "evolution archive is invalid or exceeds the bounded size"
                )
            append_started = True
            view = memoryview(encoded_line)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("archive append made no progress")
                written += count
            validate_publication_inputs()
            os.fsync(descriptor)
            validate_publication_inputs()
            after = os.fstat(descriptor)
            current = os.stat(
                self.archive_path.name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_nlink != 1
                or after.st_size != pre_append_size + len(encoded_line)
                or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise OSError("archive publication identity changed")
            os.fsync(root_descriptor)
            validate_publication_inputs()
        except EvolutionError:
            if descriptor is not None and append_started:
                try:
                    if root_descriptor is None:
                        raise OSError("archive append root descriptor is unavailable")
                    _rollback_appended_regular_file(
                        descriptor,
                        root_descriptor,
                        self.archive_path.name,
                        pre_append_size,
                    )
                except OSError as rollback_exc:
                    raise _CandidateArchivePublicationUnknown(
                        "ordinary_candidate_archive_publication_unknown"
                    ) from rollback_exc
            raise
        except OSError as exc:
            if descriptor is None or not append_started:
                raise EvolutionError("ordinary_candidate_archive_persist_failed") from exc
            try:
                if root_descriptor is None:
                    raise OSError("archive append root descriptor is unavailable")
                _rollback_appended_regular_file(
                    descriptor,
                    root_descriptor,
                    self.archive_path.name,
                    pre_append_size,
                )
            except OSError as rollback_exc:
                raise _CandidateArchivePublicationUnknown(
                    "ordinary_candidate_archive_publication_unknown"
                ) from rollback_exc
            raise EvolutionError("ordinary_candidate_archive_persist_failed") from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if root_descriptor is not None:
                try:
                    os.close(root_descriptor)
                except OSError:
                    pass
        return candidate

    def _seed_authority(
        self,
        prepared: Sequence[_PreparedInitialSeed],
        *,
        contract_sha256: str,
        evaluator_fingerprint: str | None,
    ) -> None:
        if not isinstance(contract_sha256, str) or not _SHA256.fullmatch(contract_sha256):
            raise EvolutionError("verified_seed_context_invalid")
        if evaluator_fingerprint is None or not _SHA256.fullmatch(evaluator_fingerprint):
            raise EvolutionError("verified_seed_context_invalid")
        if any(
            item.receipt["contract_sha256"] != contract_sha256
            or item.receipt["evaluator_fingerprint"] != evaluator_fingerprint
            for item in prepared
        ):
            raise EvolutionError("verified_seed_context_mismatch")

    @staticmethod
    def _write_private_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise EvolutionError("verified_seed_commit_failed")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            view = memoryview(content)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    @classmethod
    def _write_private_text(cls, path: Path, content: str) -> None:
        cls._write_private_bytes(path, content.encode("utf-8"))

    def _seed_contract_for_commit(self, contract_sha256: str) -> bytes | None:
        if not self._path_present(self.root):
            return None
        if self.root.is_symlink() or not self.root.is_dir():
            raise EvolutionError("verified_seed_initialization_requires_empty_archive")
        try:
            entries = tuple(self.root.iterdir())
        except OSError as exc:
            raise EvolutionError("verified_seed_initialization_requires_empty_archive") from exc
        if len(entries) != 1 or entries[0].name != "contract.json":
            raise EvolutionError("verified_seed_initialization_requires_empty_archive")
        content, digest = self._canonical_contract_snapshot(entries[0])
        if digest != contract_sha256:
            raise EvolutionError("verified_seed_context_mismatch")
        return content

    def _preflight_seed_commit_root(self, contract_sha256: str) -> bytes | None:
        """Validate every durable root prerequisite before external seed production."""

        contract_content = self._seed_contract_for_commit(contract_sha256)
        if self._path_present(self.seed_stage_path) or self._path_present(
            self.seed_backup_path
        ):
            raise EvolutionError("verified_seed_recovery_ambiguous")
        return contract_content

    def commit_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
        *,
        state: dict[str, Any],
        contract_sha256: str,
        evaluator_fingerprint: str | None,
        canonical_strategy: Literal["population", "openevolve"] = "population",
    ) -> tuple[Candidate, ...]:
        """Publish a fully adjudicated seed batch through a directory transaction.

        Every source, candidate record, receipt sidecar, archive line, state snapshot, and commit
        marker is built below a private sibling directory. If a controller has already written the
        canonical contract, its exact bytes are moved through a private backup and restored on a
        failed publication.
        """

        self._require_writable()
        self._guard_active_write(canonical_strategy)
        self._guard_seed_state_strategy(state, canonical_strategy)

        prepared = _prepare_initial_seeds(
            seeds,
            canonical_strategy=canonical_strategy,
        )
        self._seed_authority(
            prepared,
            contract_sha256=contract_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
        )
        contract_content = self._preflight_seed_commit_root(contract_sha256)
        if not isinstance(state, dict) or "seed_admission" in state:
            raise EvolutionError("verified_seed_state_invalid")
        candidate_ids = {item.candidate.candidate_id for item in prepared}
        if canonical_strategy == "population":
            active_ids = state.get("active_ids")
            if not isinstance(active_ids, dict):
                raise EvolutionError("verified_seed_state_invalid")
            active_flat = [
                candidate_id
                for values in active_ids.values()
                if isinstance(values, list)
                for candidate_id in values
            ]
            if (
                any(not isinstance(values, list) for values in active_ids.values())
                or len(active_flat) != len(set(active_flat))
                or set(active_flat) != candidate_ids
            ):
                raise EvolutionError("verified_seed_state_invalid")
        elif (
            canonical_strategy != "openevolve"
            or len(candidate_ids) != 1
            or state.get("strategy") != "openevolve"
            or state.get("status") != "completed"
            or state.get("iteration") != 1
            or state.get("best_candidate_id") not in candidate_ids
            or "active_ids" in state
        ):
            raise EvolutionError("verified_seed_state_invalid")

        summary = _seed_admission_summary(prepared)
        state_payload = {**state, "seed_admission": summary}
        state_text = json.dumps(
            state_payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        if len(state_text.encode("utf-8")) > MAX_STATE_BYTES:
            raise EvolutionError("verified seed state exceeds the bounded state size")

        ordered = tuple(sorted(prepared, key=lambda item: item.candidate.candidate_id))
        archive_lines = [
            json.dumps(
                item.candidate.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            for item in ordered
        ]
        if any(len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES for line in archive_lines):
            raise EvolutionError("verified seed archive record exceeds the bounded size")
        marker_payload = {
            "schema_version": "1",
            "admission_sha256": summary["admission_sha256"],
            "candidate_ids": [item.candidate.candidate_id for item in ordered],
            "seed_candidates_sha256": _canonical_seed_sha256(
                [item.candidate.to_dict() for item in ordered]
            ),
        }
        marker = {
            **marker_payload,
            "commit_sha256": _canonical_seed_sha256(marker_payload),
        }
        marker_text = json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"

        try:
            self.seed_stage_path.mkdir(mode=0o700)
        except OSError as exc:
            raise EvolutionError("verified_seed_commit_failed") from exc
        stage = self.seed_stage_path
        root_moved = False
        try:
            os.chmod(stage, 0o700)
            stage_candidates = stage / "candidates"
            stage_candidates.mkdir(mode=0o700)
            if contract_content is not None:
                self._write_private_bytes(stage / "contract.json", contract_content)
            for item in ordered:
                candidate_path = stage / Path(item.candidate.code_path).relative_to("evolution")
                self._write_private_text(candidate_path, item.source)
                evidence = {
                    "schema_version": "1",
                    "provenance": item.candidate.metadata["seed_handoff"]["provenance"],
                    "external_evidence": item.provenance["external_evidence"],
                    "provenance_sha256": _canonical_seed_sha256(item.provenance),
                    "handoff_sha256": item.handoff_sha256,
                    "receipt_sha256": item.receipt["receipt_sha256"],
                }
                record_payload = {
                    **item.candidate.to_dict(),
                    "seed_handoff_evidence": evidence,
                }
                record_text = json.dumps(
                    record_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                receipt_text = json.dumps(
                    item.receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                if (
                    len(record_text.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                    or len(receipt_text.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                ):
                    raise EvolutionError("verified seed evidence exceeds the bounded size")
                self._write_private_text(candidate_path.parent / "record.json", record_text)
                self._write_private_text(candidate_path.parent / "receipt.json", receipt_text)
            self._write_private_text(stage / "archive.jsonl", "\n".join(archive_lines) + "\n")
            self._write_private_text(stage / "state.json", state_text)
            self._write_private_text(stage / "seed-commit.json", marker_text)
            if contract_content is not None:
                current_contract = self._seed_contract_for_commit(contract_sha256)
                if current_contract != contract_content:
                    raise EvolutionError("verified_seed_contract_changed")
                if self._path_present(self.seed_backup_path):
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                os.replace(self.root, self.seed_backup_path)
                root_moved = True
                backup_contract, backup_digest = self._contract_only_snapshot(
                    self.seed_backup_path
                )
                if backup_contract != contract_content or backup_digest != contract_sha256:
                    raise EvolutionError("verified_seed_contract_changed")
            os.replace(stage, self.root)
        except Exception as exc:
            if root_moved and not self._path_present(self.root):
                try:
                    os.replace(self.seed_backup_path, self.root)
                    root_moved = False
                except OSError:
                    pass
            if stage.exists() and not stage.is_symlink():
                shutil.rmtree(stage, ignore_errors=True)
            if isinstance(exc, EvolutionError):
                raise
            raise EvolutionError("verified_seed_commit_failed") from exc
        if root_moved and self.seed_backup_path.exists():
            try:
                shutil.rmtree(self.seed_backup_path)
            except OSError:
                # The committed tree is canonical. A recognizable backup can be removed safely
                # by the next CandidateArchive initialization after an interruption here.
                pass
        return tuple(item.candidate for item in ordered)

    @staticmethod
    def _read_seed_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("verified_seed_resume_mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvolutionError("verified_seed_resume_mismatch")
        return payload

    def validate_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
        *,
        state: dict[str, Any],
        contract_sha256: str,
        evaluator_fingerprint: str | None,
        canonical_strategy: Literal["population", "openevolve"] = "population",
    ) -> tuple[Candidate, ...]:
        """Fail closed unless fresh admissions exactly match the persisted seed transaction."""

        try:
            self._guard_active_write(canonical_strategy)
            self._guard_seed_state_strategy(state, canonical_strategy)
            prepared = _prepare_initial_seeds(
                seeds,
                canonical_strategy=canonical_strategy,
            )
            self._seed_authority(
                prepared,
                contract_sha256=contract_sha256,
                evaluator_fingerprint=evaluator_fingerprint,
            )
            summary = _seed_admission_summary(prepared)
            if state.get("seed_admission") != summary:
                raise EvolutionError("verified_seed_resume_mismatch")
            marker = self._read_seed_json(self.seed_commit_path)
            if set(marker) != {
                "schema_version",
                "admission_sha256",
                "candidate_ids",
                "seed_candidates_sha256",
                "commit_sha256",
            }:
                raise EvolutionError("verified_seed_resume_mismatch")
            marker_payload = {
                key: item for key, item in marker.items() if key != "commit_sha256"
            }
            if (
                marker["schema_version"] != "1"
                or marker["admission_sha256"] != summary["admission_sha256"]
                or marker["commit_sha256"] != _canonical_seed_sha256(marker_payload)
            ):
                raise EvolutionError("verified_seed_resume_mismatch")

            archive = {item.candidate_id: item for item in self.records()}
            expected_ids = {item.candidate.candidate_id for item in prepared}
            archived_seed_ids = {
                candidate.candidate_id
                for candidate in archive.values()
                if self._is_seed_candidate(candidate)
            }
            if (
                set(marker["candidate_ids"]) != expected_ids
                or archived_seed_ids != expected_ids
                or not expected_ids <= set(archive)
            ):
                raise EvolutionError("verified_seed_resume_mismatch")
            persisted_seed_candidates = [
                archive[candidate_id].to_dict() for candidate_id in sorted(expected_ids)
            ]
            if marker["seed_candidates_sha256"] != _canonical_seed_sha256(
                persisted_seed_candidates
            ):
                raise EvolutionError("verified_seed_resume_mismatch")

            current_by_id = {item.candidate.candidate_id: item for item in prepared}
            for candidate_id in sorted(expected_ids):
                current = current_by_id[candidate_id]
                persisted = archive[candidate_id]
                if (
                    persisted.parent_id != current.candidate.parent_id
                    or persisted.generation != current.candidate.generation
                    or persisted.iteration != current.candidate.iteration
                    or persisted.strategy != current.candidate.strategy
                    or persisted.island_id != current.candidate.island_id
                    or persisted.evaluation.to_dict() != current.candidate.evaluation.to_dict()
                    or persisted.metadata != current.candidate.metadata
                ):
                    raise EvolutionError("verified_seed_resume_mismatch")
                source_path = _confined(
                    self.workspace,
                    self.workspace / persisted.code_path,
                    "verified seed source path",
                )
                _reject_symlink_components(
                    source_path,
                    self.candidates_root,
                    "verified seed source path",
                )
                if source_path.is_symlink() or not source_path.is_file():
                    raise EvolutionError("verified_seed_resume_mismatch")
                source_bytes = source_path.read_bytes()
                if (
                    len(source_bytes) > MAX_SOURCE_BYTES
                    or source_bytes != current.source.encode("utf-8")
                    or hashlib.sha256(source_bytes).hexdigest()
                    != current.receipt["source_sha256"]
                ):
                    raise EvolutionError("verified_seed_resume_mismatch")
                record = self._read_seed_json(source_path.parent / "record.json")
                receipt = self._read_seed_json(source_path.parent / "receipt.json")
                candidate_payload = persisted.to_dict()
                if any(record.get(key) != item for key, item in candidate_payload.items()):
                    raise EvolutionError("verified_seed_resume_mismatch")
                if set(record) != {*candidate_payload, "seed_handoff_evidence"}:
                    raise EvolutionError("verified_seed_resume_mismatch")
                evidence = record["seed_handoff_evidence"]
                expected_evidence = {
                    "schema_version": "1",
                    "provenance": current.candidate.metadata["seed_handoff"]["provenance"],
                    "external_evidence": current.provenance["external_evidence"],
                    "provenance_sha256": _canonical_seed_sha256(current.provenance),
                    "handoff_sha256": current.handoff_sha256,
                    "receipt_sha256": current.receipt["receipt_sha256"],
                }
                if evidence != expected_evidence or receipt != current.receipt:
                    raise EvolutionError("verified_seed_resume_mismatch")
            return tuple(archive[candidate_id] for candidate_id in sorted(expected_ids))
        except EvolutionError:
            raise
        except Exception as exc:
            raise EvolutionError("verified_seed_resume_mismatch") from exc

    def best(self) -> Candidate | None:
        valid = [candidate for candidate in self.records() if candidate.evaluation.validity == 1]
        if not valid:
            return None
        return max(valid, key=lambda candidate: candidate.evaluation.combined_score)

    def write_state(self, payload: dict[str, Any]) -> None:
        self._guard_producer_publication_recovery()
        self._require_writable()
        strategy = payload.get("strategy", _MISSING_STRATEGY)
        selected_strategy = self._guard_active_write(strategy)
        selected_strategy = selected_strategy or "population"
        if "config" in payload:
            config = payload["config"]
            if not isinstance(config, dict) or "strategy" not in config:
                raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
            config_strategy = config["strategy"]
            if config_strategy == "loop":
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            if (
                not isinstance(config_strategy, str)
                or config_strategy not in ACTIVE_EVOLUTION_STRATEGIES
            ):
                raise EvolutionError(_WORKSPACE_STRATEGY_INVALID)
            if config_strategy != selected_strategy:
                raise EvolutionError(_WORKSPACE_STRATEGY_MISMATCH)
        state_payload = (
            payload
            if strategy is not _MISSING_STRATEGY
            else {**payload, "strategy": selected_strategy}
        )
        try:
            encoded = (
                json.dumps(
                    state_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            raise EvolutionError("evolution state must be finite JSON") from exc
        if len(encoded) > MAX_STATE_BYTES:
            raise EvolutionError("evolution state exceeds the bounded state size")
        if (
            (self.state_path.exists() or self.state_path.is_symlink())
            and (self.state_path.is_symlink() or not self.state_path.is_file())
        ):
            raise EvolutionError("evolution state must be a regular file")
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        if temporary.is_symlink() or (temporary.exists() and not temporary.is_file()):
            raise EvolutionError("evolution state persist failed")
        self._ensure_layout()
        if temporary.exists():
            try:
                # A regular fixed temp can remain after fsync and before replace. Unlinking this
                # workspace entry is safe even when it is a hardlink to another pathname.
                temporary.unlink()
                _fsync_directory(
                    self.state_path.parent,
                    error="evolution state persist failed",
                )
            except OSError as exc:
                raise EvolutionError("evolution state persist failed") from exc
        self._atomic_write_bytes(
            self.state_path,
            encoded,
            error="evolution state persist failed",
        )

    def read_state(self) -> dict[str, Any]:
        self._guard_producer_publication_recovery()
        if not self.state_path.exists():
            if self.state_path.is_symlink():
                raise EvolutionError("evolution state is invalid or exceeds the bounded size")
            return {}
        if (
            self.state_path.is_symlink()
            or not self.state_path.is_file()
            or self.state_path.stat().st_size > MAX_STATE_BYTES
        ):
            raise EvolutionError("evolution state is invalid or exceeds the bounded size")
        payload = json.loads(
            _read_bounded_regular_file(
                self.state_path,
                MAX_STATE_BYTES,
                error="evolution state is invalid or exceeds the bounded size",
            ).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise EvolutionError("evolution state must be an object")
        return payload

    def result(self, strategy: str, status: str, iterations: int, error: str | None = None) -> StrategyResult:
        records = self.records()
        if strategy not in EVOLUTION_STRATEGIES:
            raise EvolutionError("unsupported evolution result strategy")
        state = self.read_state()
        state_strategy = state.get("strategy") if state else None
        archived_strategies = {candidate.strategy for candidate in records}
        if state and state_strategy != strategy:
            if "loop" in {state_strategy, strategy}:
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            raise EvolutionError("evolution result strategy does not match the persisted state")
        if archived_strategies - {strategy}:
            if "loop" in archived_strategies or strategy == "loop":
                raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
            raise EvolutionError("evolution result strategy does not match the candidate archive")
        best = self.best()
        best_path: str | None = None
        if best is not None:
            raw_path = self.workspace / best.code_path
            try:
                _reject_symlink_components(raw_path, self.workspace, "best candidate path")
                resolved = _confined(self.workspace, raw_path, "best candidate path")
                if not resolved.is_file() or resolved.is_symlink():
                    raise EvolutionError("best candidate path is not a regular file")
                best_path = resolved.relative_to(self.workspace).as_posix()
            except (OSError, ValueError, EvolutionError):
                # A stale or tampered archive record must never hand an unverified source to a
                # parent Agent. Treat the selected candidate as unavailable for this result.
                best = None
        return StrategyResult(
            strategy=strategy,
            status=status,  # type: ignore[arg-type]
            iterations=max(0, iterations),
            evaluated_candidates=len(records),
            valid_candidates=sum(item.evaluation.validity == 1 for item in records),
            best_candidate_id=best.candidate_id if best else None,
            best_score=best.evaluation.combined_score if best else None,
            archive_path=self.archive_path.relative_to(self.workspace).as_posix(),
            error=_bounded_error(error) if error else None,
            best_candidate_path=best_path,
        )


def _report(value: EvaluationReport | dict[str, Any]) -> EvaluationReport:
    if isinstance(value, EvaluationReport):
        payload = value.to_dict()
    elif isinstance(value, dict):
        payload = value
    else:
        raise EvolutionError("evaluator must return an EvaluationReport or object")
    try:
        # EvaluationReport is frozen only at its top level. Snapshot nested score/error mappings at
        # the callback return boundary so a producer-owned object cannot change later durable bytes.
        snapshot = json.loads(_canonical_json_bytes(payload).decode("utf-8"))
        return EvaluationReport.from_dict(snapshot)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvolutionError("evaluator returned an invalid EvaluationReport") from exc


def _invalid_report(message: object) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "local-evaluator",
            "validity": 0,
            "combined_score": 0,
            "detailed_scores": {},
            "error_info": [{"code": "evaluation_error", "message": _bounded_error(message)[:512]}],
        }
    )


def _caused_by_timeout(error: BaseException) -> bool:
    """Classify a timeout from exception types only, without inspecting secret-bearing prose."""

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, (TimeoutError, subprocess.TimeoutExpired)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _caused_by_worker_unknown(error: BaseException) -> bool:
    """Recognize only an explicit typed worker-uncertainty signal in the cause chain."""

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, WorkerUnknownError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _evaluator_failure_code(error: BaseException) -> str:
    """Map an evaluator boundary exception to a fixed durable outcome code."""

    if _caused_by_worker_unknown(error):
        return "worker_unknown"
    if _caused_by_timeout(error):
        return "evaluator_timeout"
    return "run_failed"


class ExecutionAwareCandidateEvaluator:
    """Compose candidate execution with an existing independent evaluator.

    The wrapped evaluator keeps its historical ``(candidate_path, contract)`` signature and can
    inspect the sibling ``execution.json`` evidence. A valid evaluator report is never allowed to
    override a runner failure.
    """

    def __init__(self, runner: CandidateRunner, evaluator: CandidateEvaluator) -> None:
        if not callable(getattr(runner, "run", None)):
            raise TypeError("runner must implement run")
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        self.runner = runner
        self.evaluator = evaluator
        self._remaining_timeout: Callable[[str], float] | None = None

    def set_remaining_timeout(self, callback: Callable[[str], float] | None) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("remaining timeout callback must be callable or None")
        self._remaining_timeout = callback
        setter = getattr(self.evaluator, "set_remaining_timeout", None)
        if callable(setter):
            setter(callback)

    def set_observer(self, observer: Callable[[str, dict[str, Any]], None] | None) -> None:
        """Forward optional Agent evidence observation through the execution wrapper."""
        setter = getattr(self.evaluator, "set_observer", None)
        if callable(setter):
            setter(observer)

    def __call__(
        self, candidate_path: Path, contract: AlgorithmProblemContract
    ) -> EvaluationReport:
        candidate = Path(candidate_path).expanduser().resolve(strict=False)
        workspace = candidate.parent
        timeout = None
        if self._remaining_timeout is not None:
            remaining = self._remaining_timeout("candidate_execution")
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(float(remaining)) or remaining <= 0:
                raise EvolutionError("automatic solve execution budget exhausted")
            timeout = float(remaining)
        try:
            execution = (
                self.runner.run(candidate, workspace)
                if timeout is None else self.runner.run(candidate, workspace, timeout=timeout)
            )
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception as exc:  # noqa: BLE001 - runner is an injected local boundary
            execution = CandidateExecution(
                status="failed",
                exit_code=None,
                duration_ms=0,
                error="runner_failed",
                stderr=_bounded_output(str(exc), MAX_EXECUTION_OUTPUT_BYTES),
            )
            _write_execution_evidence(workspace, execution)
        if self._remaining_timeout is not None:
            self._remaining_timeout("evaluation")
        if execution.status != "succeeded":
            detail = execution.error or f"execution_{execution.status}"
            return _invalid_report(detail)
        report = _report(self.evaluator(candidate, contract))
        if self._remaining_timeout is not None:
            self._remaining_timeout("evaluation")
        return report


def _drafts(value: CandidateDraft | Sequence[CandidateDraft]) -> tuple[CandidateDraft, ...]:
    if isinstance(value, CandidateDraft):
        return (value,)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise EvolutionError("generator must return CandidateDraft or a sequence of drafts")
    output = tuple(value)
    if not output or any(not isinstance(item, CandidateDraft) for item in output):
        raise EvolutionError("generator returned no valid candidate drafts")
    return output


class _BaseStrategy:
    name: Literal["population", "openevolve"]

    def __init__(self, context: EvolutionContext, *, read_only: bool = False) -> None:
        if context.contract.evolution.strategy == "loop":
            raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if context.config.strategy != self.name:
            raise EvolutionError(_WORKSPACE_STRATEGY_MISMATCH)
        self.context = context
        self.archive = CandidateArchive(
            context.workspace, requested_strategy=self.name, read_only=read_only,
        )
        # Root-only evidence does not enter seed-recovery preflight. Inspect it before resolving
        # adapters or binding observers so a retired, malformed, or cross-strategy workspace can
        # never trigger generator/evaluator behavior on a fresh strategy object.
        self.archive._guard_active_write(self.name)
        self.config = context.config
        self.integrity_authority = resolve_candidate_integrity_authority(context)
        if context.bundle_pipeline is not None:
            context.bundle_pipeline.validate_context(context, self.integrity_authority)
        # Keep the evaluator's structured feedback available to a generator during this live
        # process while persisting only the receipt-safe projection.  The map is deliberately
        # in-memory and is empty on resume, so evaluator prose cannot cross the durable boundary.
        self._transient_evaluations: dict[str, EvaluationReport] = {}
        if read_only:
            return
        self._bind_observer(context.generate)
        self._bind_observer(context.evaluate)
        self._bind_timeout(context.generate)
        self._bind_timeout(context.evaluate)
        self._bind_timeout(context.bundle_pipeline)
        self._bind_process_ownership(context.bundle_pipeline)
        setter = getattr(context.bundle_pipeline, "set_continuation_guard", None)
        if callable(setter):
            setter(context.continuation_guard)

    def _bind_timeout(self, target: object) -> None:
        if target is None:
            return
        setter = getattr(target, "set_remaining_timeout", None)
        if callable(setter):
            setter(self.context.remaining_timeout)

    def _bind_process_ownership(self, target: object) -> None:
        if target is None:
            return
        setter = getattr(target, "set_process_observer", None)
        if callable(setter):
            setter(self.context.process_observer, self.context.process_released)

    def _check_stage(self, stage: str) -> None:
        if self.context.continuation_guard is not None:
            self.context.continuation_guard()
        callback = self.context.remaining_timeout
        if callback is not None:
            remaining = callback(stage)
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(float(remaining)) or remaining <= 0:
                raise EvolutionError("automatic solve execution budget exhausted")

    def _bind_observer(self, target: object) -> None:
        setter = getattr(target, "set_observer", None)
        if callable(setter):
            setter(self.context.observe)

    def _cancelled(self) -> bool:
        try:
            return bool(self.context.cancelled())
        except Exception:  # noqa: BLE001 - cancellation callback is an external boundary
            return True

    def _discard_unarchived_candidate(self, candidate_id: str) -> None:
        """Remove a source tree that was staged before an archive record existed."""

        path = self.archive.candidates_root / candidate_id
        try:
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
        except OSError:
            # The durable archive remains authoritative. A missing staging tree is safe to
            # treat as already discarded; a later resume must never infer a candidate from it.
            pass

    def _generation_candidate(self, candidate: Candidate | None) -> Candidate | None:
        """Overlay live evaluator feedback without changing the canonical archive record."""

        if candidate is None:
            return None
        evaluation = self._transient_evaluations.get(candidate.candidate_id)
        if evaluation is None:
            return candidate
        return replace(candidate, evaluation=evaluation)

    def _generation_records(self) -> tuple[Candidate, ...]:
        """Return archive records with process-local feedback overlays for the next proposal."""

        return tuple(
            self._generation_candidate(candidate)  # type: ignore[arg-type]
            for candidate in self.archive.records()
        )

    def _persist(
        self,
        draft: CandidateDraft,
        *,
        iteration: int,
        generation: int,
        parent: Candidate | None,
        island_id: int | None,
    ) -> Candidate:
        self._check_stage("candidate_persistence")
        if self.context.bundle_pipeline is not None:
            candidate = self.context.bundle_pipeline.persist(
                self, draft, iteration=iteration, generation=generation, parent=parent,
                island_id=island_id,
            )
            self._check_stage("candidate_persistence")
            return candidate
        if draft.source_files is not None:
            raise _InitialCandidateFailure("candidate_failed")
        candidate_id = self.archive.next_id()
        source_snapshot: _HeldRegularFileSnapshot | None = None
        execution_snapshot: _HeldRegularFileSnapshot | None = None
        # Candidate IDs are derived only from published archive lines.  Remove any unarchived
        # tree left by an earlier local crash before reusing the ID so stale execution evidence or
        # outputs cannot be attributed to the new evaluator call.
        self._discard_unarchived_candidate(candidate_id)
        try:
            path = self.archive.candidate_source_path(candidate_id, draft.filename)
            source_bytes = draft.source.encode("utf-8")
            self.archive._atomic_write_bytes(
                path,
                source_bytes,
                error="ordinary_candidate_source_changed",
            )
            _reject_symlink_components(path, self.archive.candidates_root, "candidate path")
            source_snapshot = _HeldRegularFileSnapshot.open(
                path,
                MAX_SOURCE_BYTES,
                error="ordinary_candidate_source_changed",
            )
            if source_snapshot.content != source_bytes:
                raise EvolutionError("ordinary_candidate_source_changed")
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            if source_snapshot is not None:
                source_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise
        except Exception:  # noqa: BLE001 - candidate staging is a fixed boundary
            if source_snapshot is not None:
                source_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise _InitialCandidateFailure("candidate_failed") from None
        try:
            self._check_stage("evaluation")
            evaluation = _report(self.context.evaluate(path, self.context.contract))
            self._check_stage("evaluation")
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            if source_snapshot is not None:
                source_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise
        except Exception as exc:  # noqa: BLE001 - evaluator is an injected boundary
            if source_snapshot is not None:
                source_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            # Do not persist evaluator exception prose in either the synthetic report or
            # candidate metadata. Initialization has no offspring journal entry, so the caller
            # records the same fixed code in terminal state when the whole initial population
            # fails.
            raise _InitialCandidateFailure(_evaluator_failure_code(exc)) from None
        try:
            _reject_symlink_components(path, self.archive.candidates_root, "candidate path")
            assert source_snapshot is not None
            source_snapshot.validate(source_bytes)
            execution_snapshot = self.archive._candidate_execution_snapshot(path)
            if execution_snapshot is None:
                execution_digest = None
            else:
                execution_snapshot.validate(execution_snapshot.content)
                execution_digest = hashlib.sha256(execution_snapshot.content).hexdigest()
        except (OSError, EvolutionError):
            if source_snapshot is not None:
                source_snapshot.close()
            if execution_snapshot is not None:
                execution_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise _InitialCandidateFailure("candidate_failed") from None
        try:
            self._check_stage("candidate_persistence")
            candidate = self.archive.persist(
                draft,
                candidate_id=candidate_id,
                strategy=self.name,
                iteration=iteration,
                generation=generation,
                parent_id=parent.candidate_id if parent else None,
                island_id=island_id,
                evaluation=evaluation,
                integrity_authority=self.integrity_authority,
                execution_sha256=execution_digest,
                source_snapshot=source_snapshot,
                execution_snapshot=execution_snapshot,
            )
        except _CandidateArchivePublicationUnknown:
            # The complete source and sidecars are the only recoverable evidence when an archive
            # append cannot be confirmed or rolled back.  Never delete them in this ambiguity.
            raise
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            if source_snapshot is not None:
                source_snapshot.close()
            if execution_snapshot is not None:
                execution_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise
        except Exception:  # noqa: BLE001 - persistence has one fixed candidate outcome
            if source_snapshot is not None:
                source_snapshot.close()
            if execution_snapshot is not None:
                execution_snapshot.close()
            self._discard_unarchived_candidate(candidate_id)
            raise _InitialCandidateFailure("candidate_failed") from None
        finally:
            if source_snapshot is not None:
                source_snapshot.close()
            if execution_snapshot is not None:
                execution_snapshot.close()
        self._transient_evaluations[candidate.candidate_id] = evaluation
        self._check_stage("candidate_persistence")
        try:
            self.context.observe("candidate", candidate.to_dict())
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc
        return candidate

    def _state_payload(self, status: str, iteration: int, **extra: Any) -> dict[str, Any]:
        payload = {
            "schema_version": "1",
            "strategy": self.name,
            "status": status,
            "iteration": iteration,
            "contract_sha256": self.context.contract.digest(),
            "config": self.config.to_dict(),
            **extra,
        }
        existing = self.archive.read_state()
        # Imported seed and OpenEvolve transactions retain their established state shape.  Once a
        # native ordinary candidate is being prepared, attach the additive integrity markers to
        # subsequent snapshots.  ``pending_offspring`` is emitted before the first offspring is
        # staged, so a seeded run still has an authority/digest baseline if it crashes after a
        # complete candidate batch but before its final state snapshot.  The seed-only commit
        # snapshot remains byte-compatible because it has neither ordinary records nor pending
        # offspring.
        if self.name == "population" and (
            not self.context.initial_seeds
            or "pending_offspring" in extra
            or existing.get("candidate_integrity_schema_version")
            == CANDIDATE_INTEGRITY_SCHEMA_VERSION
            or any(
                not self.archive._is_seed_candidate(candidate)
                for candidate in self.archive.records()
            )
        ):
            payload.update(
                {
                    "candidate_integrity_schema_version": CANDIDATE_INTEGRITY_SCHEMA_VERSION,
                    "candidate_integrity_authority": self.integrity_authority.to_dict(),
                    "candidate_archive_sha256": self.archive._candidate_archive_digest(),
                }
            )
        seed_admission = existing.get("seed_admission")
        if seed_admission is not None:
            payload["seed_admission"] = seed_admission
        producer_admissions = existing.get("producer_admissions")
        if producer_admissions is not None:
            payload["producer_admissions"] = producer_admissions
        for name in (
            "outcome_schema_version",
            "outcome_start_iteration",
            "outcome_watermark",
            "outcome_watermark_sha256",
            "outcome_archive_baseline_sha256",
            "failed_offspring_iteration",
            "failed_offspring_sha256",
        ):
            if name in existing and name not in payload:
                payload[name] = existing[name]
        return payload

    def _state(self, status: str, iteration: int, **extra: Any) -> None:
        payload = self._state_payload(status, iteration, **extra)
        self._check_stage("selection")
        self.archive.write_state(payload)
        try:
            self.context.observe("state", payload)
        except Exception as exc:  # noqa: BLE001 - an audit sink must not stop local search
            # The archive/state files are still canonical for standalone callers.  Keep the
            # strategy usable when an optional observer (for example a parent process) disappears.
            del exc

    def _load_state(self) -> dict[str, Any]:
        state = self.archive.read_state()
        if not state:
            return state
        if state.get("strategy") != self.name:
            raise EvolutionError("evolution state strategy does not match the requested strategy")
        digest = state.get("contract_sha256")
        if digest != self.context.contract.digest():
            raise EvolutionError("evolution state contract digest does not match the supplied contract")
        stored_config_present = "config" in state
        stored_config = state.get("config")
        if (
            CANDIDATE_INTEGRITY_SCHEMA_VERSION
            == state.get("candidate_integrity_schema_version")
            and (not stored_config_present or stored_config is None)
        ) or (
            stored_config is not None
            and _canonical_json_bytes(stored_config)
            != _canonical_json_bytes(self.config.to_dict())
        ):
            raise EvolutionError(
                "evolution state configuration does not match the supplied configuration"
            )
        return state

    def _allowed_delayed_root_ids(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
        *,
        outcome_history_validated: bool,
    ) -> frozenset[str]:
        """Return lineage exceptions proven by a strategy-specific durable journal."""

        del state, records, outcome_history_validated
        return frozenset()

    def _pending_candidate_archive_extension_matches(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
    ) -> bool:
        """Accept only the exact evaluated suffix of a completely published pending batch."""

        pending = state.get("pending_offspring")
        if not isinstance(pending, dict):
            return False
        attempt_count = pending.get("attempt_count")
        target_iteration = pending.get("iteration")
        if (
            isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or isinstance(target_iteration, bool)
            or not isinstance(target_iteration, int)
        ):
            return False
        try:
            outcomes = sorted(
                (
                    item
                    for item in self.archive.offspring_outcomes()
                    if item.iteration == target_iteration
                ),
                key=lambda item: item.attempt,
            )
        except EvolutionError:
            return False
        if len(outcomes) != attempt_count or [item.attempt for item in outcomes] != list(
            range(attempt_count)
        ):
            return False
        evaluated_ids = [
            item.candidate_id for item in outcomes if item.code == "evaluated"
        ]
        if any(candidate_id is None for candidate_id in evaluated_ids):
            return False
        evaluated_id_set = set(evaluated_ids)
        baseline = [
            candidate
            for candidate in records
            if candidate.candidate_id not in evaluated_id_set
        ]
        if state.get("candidate_archive_sha256") != self.archive._candidate_archive_digest(
            baseline
        ):
            return False
        current_ids = [
            candidate.candidate_id
            for candidate in records
            if not self.archive._is_seed_candidate(candidate)
        ]
        baseline_ids = [
            candidate.candidate_id
            for candidate in baseline
            if not self.archive._is_seed_candidate(candidate)
        ]
        return current_ids == [*baseline_ids, *evaluated_ids]

    def _validate_candidate_integrity_state(
        self,
        state: Mapping[str, Any],
        *,
        outcome_history_validated: bool = False,
    ) -> None:
        """Check ordinary candidate evidence before any resume-side selection or evaluation."""

        records = self.archive.records()
        ordinary = [
            candidate
            for candidate in records
            if candidate.strategy == "population"
            and not self.archive._is_seed_candidate(candidate)
        ]
        schema_present = "candidate_integrity_schema_version" in state
        authority_present = "candidate_integrity_authority" in state
        digest_present = "candidate_archive_sha256" in state
        if schema_present != authority_present or schema_present != digest_present:
            # Once any Feature 087 marker appears the group is atomic, including zero-candidate
            # cancellation/failure states.  Silently accepting a partial group would let context
            # authority drift before the first successful candidate.
            raise EvolutionError("ordinary_candidate_integrity_state_invalid")
        if not schema_present:
            if ordinary or (state and "seed_admission" not in state):
                # Every unseeded population state emitted by this implementation carries the
                # marker group, including cancellation before the first candidate.  Requiring it
                # on any non-empty unseeded state prevents an attacker from stripping the whole
                # group and reclassifying a modern zero-candidate run as legacy state.
                raise EvolutionError(LEGACY_CANDIDATE_INTEGRITY_ERROR)
            return
        if state.get("candidate_integrity_schema_version") != CANDIDATE_INTEGRITY_SCHEMA_VERSION:
            raise EvolutionError("ordinary_candidate_integrity_state_invalid")
        authority = CandidateIntegrityAuthority.from_dict(
            state["candidate_integrity_authority"]
        )
        if authority.to_dict() != self.integrity_authority.to_dict():
            raise EvolutionError("ordinary_candidate_integrity_authority_mismatch")
        if not ordinary:
            # Seed-only archives use their own receipt/commit protocol.  Any ordinary markers are
            # still checked when present so a forged mixed state cannot silently pass.
            expected_digest = self.archive._candidate_archive_digest(records)
            if state["candidate_archive_sha256"] != expected_digest:
                raise EvolutionError("ordinary_candidate_integrity_state_invalid")
            return
        # A process may have published only a prefix of the configured offspring attempts before
        # it lost the ability to write the next outcome.  The append-only outcome gate owns that
        # recovery decision and must report its established ``population_iteration_incomplete``
        # error; do not turn the deliberately stale archive watermark into a new integrity error
        # before that gate gets to inspect the durable prefix.  The pending shape and bounds have
        # already been checked by ``_validate_outcome_history`` immediately before this method.
        pending = state.get("pending_offspring")
        if isinstance(pending, dict):
            attempt_count = pending.get("attempt_count")
            target_iteration = pending.get("iteration")
            try:
                completed = sum(
                    item.iteration == target_iteration
                    for item in self.archive.offspring_outcomes()
                )
            except EvolutionError:
                completed = attempt_count
            if (
                isinstance(attempt_count, int)
                and not isinstance(attempt_count, bool)
                and isinstance(target_iteration, int)
                and not isinstance(target_iteration, bool)
                and completed < attempt_count
            ):
                return
        delayed_root_ids = self._allowed_delayed_root_ids(
            state,
            records,
            outcome_history_validated=outcome_history_validated,
        )
        self.archive.validate_candidate_integrity(
            authority=authority,
            allowed_delayed_root_ids=delayed_root_ids,
        )
        if any(
            candidate.strategy == "population"
            and not self.archive._is_seed_candidate(candidate)
            and (
                candidate.island_id is None
                or candidate.island_id >= self.config.num_islands
            )
            for candidate in ordinary
        ):
            raise EvolutionError("ordinary_candidate_lineage_mismatch")
        expected_digest = self.archive._candidate_archive_digest(records)
        if (
            state.get("candidate_archive_sha256") != expected_digest
            and not self._pending_candidate_archive_extension_matches(state, records)
        ):
            # A process can die after a complete pending batch has published its candidate/archive
            # line but before the final state snapshot.  The outcome journal will finalize only
            # the exact evaluated suffix; an incomplete or reordered prefix remains fail-closed.
            raise EvolutionError("ordinary_candidate_archive_mismatch")

    def _terminal(self, state: dict[str, Any]) -> StrategyResult | None:
        status = state.get("status")
        if status in {"completed", "stagnated", "cancelled", "failed"}:
            return self.archive.result(self.name, status, int(state.get("iteration", 0)), state.get("error"))
        return None


class LoopStrategy:
    """Read-only compatibility marker for retired single-chain evolution.

    Historical callers may still import the public name while inspecting old archives.  New or
    resumed loop execution is rejected before any candidate or state mutation.
    """

    name: Literal["loop"] = "loop"

    def __init__(self, context: EvolutionContext) -> None:
        self.context = context

    @staticmethod
    def _retired() -> EvolutionError:
        return EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)

    def run(self) -> StrategyResult:
        raise self._retired()

    def resume(self) -> StrategyResult:
        raise self._retired()


def _tokens(
    candidate: Candidate,
    workspace: Path,
    source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
) -> set[str]:
    override = source_overrides.get(candidate.candidate_id) if source_overrides is not None else None
    if override is not None:
        try:
            text = "\n".join(value.decode("utf-8") for value in override.values())
        except (AttributeError, UnicodeDecodeError):
            return set()
        return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text))
    if candidate.bundle_evidence is not None:
        from .bundle_evolution import read_candidate_source_files

        try:
            sources = read_candidate_source_files(workspace, candidate)
        except (OSError, UnicodeDecodeError, EvolutionError):
            return set()
        return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", "\n".join(sources.values())))
    try:
        raw_path = workspace / candidate.code_path
        _reject_symlink_components(raw_path, workspace, "candidate code path")
        path = _confined(workspace, raw_path, "candidate code path")
        text = _read_bounded_regular_file(
            path,
            MAX_SOURCE_BYTES,
            error="candidate code path is invalid",
        ).decode("utf-8")
    except (OSError, UnicodeDecodeError, EvolutionError):
        return set()
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text))


def _novelty(
    candidate: Candidate,
    peers: Iterable[Candidate],
    workspace: Path,
    source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
) -> float:
    current = _tokens(candidate, workspace, source_overrides)
    if not current:
        return 0.0
    distances = []
    for peer in peers:
        other = _tokens(peer, workspace, source_overrides)
        union = current | other
        distances.append(1.0 if not union else 1.0 - len(current & other) / len(union))
    return min(distances, default=1.0)


class PopulationStrategy(_BaseStrategy):
    """Bounded local population search with optional islands and ring migration."""

    name: Literal["population"] = "population"

    def __init__(self, context: EvolutionContext, *, read_only: bool = False) -> None:
        super().__init__(context, read_only=read_only)
        self.rng = random.Random(self.config.rng_seed)

    @staticmethod
    def _outcome_digest(outcomes: Iterable[OffspringOutcome]) -> str:
        ordered = sorted(outcomes, key=lambda item: (item.iteration, item.attempt))
        return _canonical_seed_sha256([item.to_dict() for item in ordered])

    @staticmethod
    def _candidate_digest(candidates: Iterable[Candidate]) -> str:
        ordered = sorted(candidates, key=lambda item: item.candidate_id)
        return _canonical_seed_sha256([item.to_dict() for item in ordered])

    def _allowed_delayed_root_ids(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
        *,
        outcome_history_validated: bool,
    ) -> frozenset[str]:
        """Recognize journal-proven roots created while the active population is empty.

        Initialization or an earlier batch can publish only invalid candidates. Since invalid
        records never enter ``active_ids``, the next complete offspring batch legitimately has no
        parent and emits generation-zero roots. Bind every exception to an evaluated journal entry
        and require that no valid population candidate existed before that batch.
        """

        if not outcome_history_validated or state.get("outcome_schema_version") != "1":
            return frozenset()
        try:
            outcomes = self.archive.offspring_outcomes()
            pending = self._pending_offspring(dict(state))
        except (EvolutionError, TypeError, ValueError):
            return frozenset()
        start_iteration = state.get("outcome_start_iteration")
        watermark = state.get("outcome_watermark")
        if (
            isinstance(start_iteration, bool)
            or not isinstance(start_iteration, int)
            or isinstance(watermark, bool)
            or not isinstance(watermark, int)
        ):
            return frozenset()

        complete_iterations = set(range(start_iteration, watermark + 1))
        if pending is not None:
            pending_outcomes = [item for item in outcomes if item.iteration == pending[0]]
            if len(pending_outcomes) == pending[1]:
                complete_iterations.add(pending[0])
        evaluated = {
            (item.iteration, item.candidate_id)
            for item in outcomes
            if item.iteration in complete_iterations
            and item.code == "evaluated"
            and item.candidate_id is not None
        }
        producer_ids = self._producer_admission_ids(state, records)
        return frozenset(
            candidate.candidate_id
            for candidate in records
            if candidate.strategy == "population"
            and candidate.candidate_id not in producer_ids
            and candidate.parent_id is None
            and candidate.generation == 0
            and candidate.iteration > 0
            and (candidate.iteration, candidate.candidate_id) in evaluated
            and not any(
                earlier.strategy == "population"
                and earlier.iteration < candidate.iteration
                and earlier.evaluation.validity == 1
                for earlier in records
            )
        )

    def _capacity(self, island: int) -> int:
        base, remainder = divmod(self.config.population_size, self.config.num_islands)
        return base + (1 if island < remainder else 0)

    def _producer_admission_events(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
    ) -> tuple[tuple[int, tuple[str, ...]], ...]:
        """Validate producer imports and return their ordered replay checkpoints."""

        raw = state.get("producer_admissions")
        if raw is None:
            return ()
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", "events"}
            or raw.get("schema_version") != "1"
            or not isinstance(raw.get("events"), list)
            or not raw["events"]
            or len(raw["events"]) > 10_000
        ):
            raise EvolutionError("population_producer_admissions_invalid")
        current_iteration = state.get("iteration")
        if (
            isinstance(current_iteration, bool)
            or not isinstance(current_iteration, int)
            or current_iteration < 0
        ):
            raise EvolutionError("population_producer_admissions_invalid")

        records_by_id = {candidate.candidate_id: candidate for candidate in records}
        admitted_ids: set[str] = set()
        events: list[tuple[int, tuple[str, ...]]] = []
        previous_iteration = -1
        for event in raw["events"]:
            if (
                not isinstance(event, dict)
                or set(event) != {"after_iteration", "candidate_ids"}
            ):
                raise EvolutionError("population_producer_admissions_invalid")
            after_iteration = event["after_iteration"]
            candidate_ids = event["candidate_ids"]
            if (
                isinstance(after_iteration, bool)
                or not isinstance(after_iteration, int)
                or not 0 <= after_iteration <= current_iteration
                or after_iteration < previous_iteration
                or not isinstance(candidate_ids, list)
                or not candidate_ids
                or len(candidate_ids) > 10_000
            ):
                raise EvolutionError("population_producer_admissions_invalid")
            normalized_ids: list[str] = []
            for candidate_id in candidate_ids:
                try:
                    candidate_id = _safe_id(candidate_id, "producer admission candidate_id")
                except EvolutionError as exc:
                    raise EvolutionError("population_producer_admissions_invalid") from exc
                candidate = records_by_id.get(candidate_id)
                if (
                    candidate_id in admitted_ids
                    or candidate is None
                    or candidate.strategy != "population"
                    or candidate.iteration != 0
                    or candidate.generation != 0
                    or candidate.parent_id is not None
                    or candidate.evaluation.validity != 1
                    or candidate.island_id is None
                    or candidate.island_id >= self.config.num_islands
                    or not isinstance(candidate.metadata, dict)
                    or not isinstance(candidate.metadata.get("producer_bundle"), dict)
                ):
                    raise EvolutionError("population_producer_admissions_invalid")
                admitted_ids.add(candidate_id)
                normalized_ids.append(candidate_id)
            events.append((after_iteration, tuple(normalized_ids)))
            previous_iteration = after_iteration

        marked_ids = {
            candidate.candidate_id
            for candidate in records
            if isinstance(candidate.metadata, dict)
            and "producer_bundle" in candidate.metadata
        }
        if marked_ids != admitted_ids:
            raise EvolutionError("population_producer_admissions_invalid")
        return tuple(events)

    def _producer_admission_ids(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
    ) -> frozenset[str]:
        return frozenset(
            candidate_id
            for _after_iteration, candidate_ids in self._producer_admission_events(
                state, records
            )
            for candidate_id in candidate_ids
        )

    def _apply_producer_admissions(
        self,
        candidate_ids: Sequence[str],
        active: dict[int, list[str]],
        records_by_id: Mapping[str, Candidate],
        best_score: float | None,
        stagnation: int,
        *,
        source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
        records: Sequence[Candidate] | None = None,
    ) -> tuple[float | None, int]:
        for candidate_id in candidate_ids:
            candidate = records_by_id[candidate_id]
            assert candidate.island_id is not None
            active[candidate.island_id].append(candidate_id)
        if candidate_ids:
            self._trim(active, source_overrides=source_overrides, records=records)
            for candidate_id in candidate_ids:
                score = records_by_id[candidate_id].evaluation.combined_score
                if best_score is None or score > best_score:
                    best_score = score
                    stagnation = 0
        return best_score, stagnation

    def _initial_seed_active(
        self,
        seeds: Sequence[AdmittedSeedInput],
    ) -> dict[int, list[str]]:
        if not seeds or len(seeds) > self.config.population_size:
            raise EvolutionError("verified_seed_population_capacity_exceeded")
        active = {island: [] for island in range(self.config.num_islands)}
        seen: set[str] = set()
        try:
            ordered = sorted(seeds, key=lambda seed: seed.candidate_id)
            for seed in ordered:
                candidate_id = _safe_id(seed.candidate_id, "verified seed candidate_id")
                if candidate_id in seen:
                    raise EvolutionError("verified_seed_invalid")
                seen.add(candidate_id)
                island = seed.island_id
                if (
                    isinstance(island, bool)
                    or not isinstance(island, int)
                    or island not in active
                    or len(active[island]) >= self._capacity(island)
                ):
                    raise EvolutionError("verified_seed_island_mismatch")
                active[island].append(candidate_id)
        except EvolutionError:
            raise
        except Exception as exc:
            raise EvolutionError("verified_seed_invalid") from exc
        return active

    def _commit_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
    ) -> dict[str, Any]:
        active = self._initial_seed_active(seeds)
        prepared = tuple(
            sorted(
                _prepare_initial_seeds(seeds),
                key=lambda item: item.candidate.candidate_id,
            )
        )
        # Seed publication writes this same candidate-ID order to the archive. Keep ties aligned
        # with CandidateArchive.best(), whose score-only max retains the first archive record, so
        # every state written before or after the seed transaction has one canonical projection.
        best_seed = max(
            (item.candidate for item in prepared),
            key=lambda candidate: candidate.evaluation.combined_score,
        )
        state = self._state_payload(
            "running",
            0,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=0,
            error=None,
            best_candidate_id=best_seed.candidate_id,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=0,
        )
        candidates = self.archive.commit_initial_seeds(
            seeds,
            state=state,
            contract_sha256=self.context.contract.digest(),
            evaluator_fingerprint=self.config.evaluator_fingerprint,
        )
        for candidate in candidates:
            try:
                self.context.observe("candidate", candidate.to_dict())
            except Exception as exc:  # noqa: BLE001 - optional audit sink
                del exc
        committed_state = self.archive.read_state()
        try:
            self.context.observe("state", committed_state)
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc
        return committed_state

    def _validate_seed_integrity_authority(
        self,
        seeds: Sequence[AdmittedSeedInput],
    ) -> None:
        """Require explicit ordinary authority inputs to agree with imported seed receipts.

        Seed admission has its own receipt protocol, but any ordinary offspring created after that
        admission must remain under the same evaluator contract. ``EvolutionContext`` exposes
        optional authority overrides for controller integrations; without this check a caller
        could supply a different evaluator kind or dependency/environment identity while reusing
        otherwise valid seeds. Compare only fields carried by the seed receipt and leave runner/
        generator identities to the native ordinary authority.
        """

        shared_fields = (
            "contract_sha256",
            "evaluator_kind",
            "evaluator_fingerprint",
            "dependency_sha256",
            "environment_sha256",
        )
        for seed in seeds:
            try:
                payload = seed.receipt.to_dict()
            except Exception as exc:
                raise EvolutionError("verified_seed_invalid") from exc
            if not isinstance(payload, dict):
                raise EvolutionError("verified_seed_invalid")
            for field_name in shared_fields:
                try:
                    expected = payload.get(field_name)
                except Exception as exc:
                    raise EvolutionError("verified_seed_invalid") from exc
                if expected is None:
                    raise EvolutionError("verified_seed_invalid")
                if expected != getattr(self.integrity_authority, field_name):
                    raise EvolutionError("verified_seed_context_mismatch")

    def _seed_resume_gate(self, state: dict[str, Any]) -> dict[str, Any]:
        seeds = tuple(self.context.initial_seeds)
        if seeds:
            self._validate_seed_integrity_authority(seeds)
        existing = self.archive.records()
        has_archived_seed = any(
            self.archive._is_seed_candidate(candidate) for candidate in existing
        )
        has_summary = "seed_admission" in state
        has_marker = self.archive.seed_commit_path.exists() or self.archive.seed_commit_path.is_symlink()
        if has_marker != has_summary:
            raise EvolutionError("verified_seed_resume_mismatch")
        if state:
            if has_summary:
                if not seeds:
                    raise EvolutionError("verified_seed_resume_requires_initial_seeds")
                self.archive.validate_initial_seeds(
                    seeds,
                    state=state,
                    contract_sha256=self.context.contract.digest(),
                    evaluator_fingerprint=self.config.evaluator_fingerprint,
                )
            elif seeds:
                raise EvolutionError("verified_seed_cannot_modify_existing_population")
            elif has_archived_seed:
                # A seed-looking archive record is not admission evidence.  Without both the
                # state summary and commit marker it must not bypass ordinary receipt validation
                # or enter ranking as an imported candidate.
                raise EvolutionError("verified_seed_resume_requires_initial_seeds")
            return state
        if has_marker:
            raise EvolutionError("verified_seed_resume_mismatch")
        if seeds:
            return self._commit_initial_seeds(seeds)
        if any("seed_handoff" in candidate.metadata for candidate in existing):
            raise EvolutionError("verified_seed_resume_requires_initial_seeds")
        if existing:
            # A non-empty archive without a state snapshot is an ambiguous publication window.
            # Do not infer an active population from it, even when the files happen to contain
            # modern-looking projections.
            if any(
                not self.archive._is_seed_candidate(candidate)
                and (candidate.source_sha256 is None or candidate.receipt_sha256 is None)
                for candidate in existing
            ):
                raise EvolutionError(LEGACY_CANDIDATE_INTEGRITY_ERROR)
            raise EvolutionError("ordinary_candidate_integrity_state_missing")
        return state

    def _reconstruct_population_projection(
        self,
        state: Mapping[str, Any],
        records: Sequence[Candidate],
        *,
        source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
    ) -> tuple[dict[int, list[str]], str | None, int, int]:
        """Replay deterministic active, best, migration, and stagnation state."""

        current_iteration = state.get("iteration", 0)
        if (
            isinstance(current_iteration, bool)
            or not isinstance(current_iteration, int)
            or current_iteration < 0
        ):
            raise EvolutionError("population state projection mismatch")
        producer_events = self._producer_admission_events(state, records)
        producer_ids = {
            candidate_id
            for _after_iteration, candidate_ids in producer_events
            for candidate_id in candidate_ids
        }
        records_by_id = {candidate.candidate_id: candidate for candidate in records}
        events_by_iteration: dict[int, list[str]] = {}
        for after_iteration, candidate_ids in producer_events:
            events_by_iteration.setdefault(after_iteration, []).extend(candidate_ids)
        active = {island: [] for island in range(self.config.num_islands)}
        seeds = [candidate for candidate in records if self.archive._is_seed_candidate(candidate)]
        initial = [
            candidate
            for candidate in records
            if candidate.strategy == "population"
            and not self.archive._is_seed_candidate(candidate)
            and candidate.candidate_id not in producer_ids
            and candidate.iteration == 0
        ]
        if seeds and initial:
            raise EvolutionError("population state projection mismatch")

        if seeds:
            for candidate in sorted(seeds, key=lambda item: item.candidate_id):
                island = candidate.island_id
                if (
                    candidate.strategy != "population"
                    or candidate.evaluation.validity != 1
                    or island is None
                    or island not in active
                    or len(active[island]) >= self._capacity(island)
                ):
                    raise EvolutionError("population state projection mismatch")
                active[island].append(candidate.candidate_id)
        else:
            for candidate in initial:
                island = candidate.island_id
                if island is None or island not in active:
                    raise EvolutionError("population state projection mismatch")
                active[island].append(candidate.candidate_id)
            self._trim(active, source_overrides=source_overrides, records=records)

        initial_valid_scores = [
            candidate.evaluation.combined_score
            for candidate in records
            if candidate.strategy == "population"
            and candidate.candidate_id not in producer_ids
            and candidate.iteration == 0
            and candidate.evaluation.validity == 1
        ]
        best_score = max(initial_valid_scores, default=None)
        stagnation = 0
        last_migration_iteration = 0
        best_score, stagnation = self._apply_producer_admissions(
            events_by_iteration.get(0, ()),
            active,
            records_by_id,
            best_score,
            stagnation,
            source_overrides=source_overrides,
            records=records,
        )
        for iteration in range(1, current_iteration + 1):
            batch = [
                candidate
                for candidate in records
                if candidate.strategy == "population"
                and not self.archive._is_seed_candidate(candidate)
                and candidate.candidate_id not in producer_ids
                and candidate.iteration == iteration
            ]
            if not batch:
                raise EvolutionError("population state projection mismatch")
            for candidate in batch:
                island = candidate.island_id
                if island is None or island not in active:
                    raise EvolutionError("population state projection mismatch")
                active[island].append(candidate.candidate_id)
            self._trim(active)
            if self._migrate(active, iteration):
                last_migration_iteration = iteration
            iteration_valid_scores = [
                candidate.evaluation.combined_score
                for candidate in batch
                if candidate.evaluation.validity == 1
            ]
            visible_scores = list(iteration_valid_scores)
            if best_score is not None:
                visible_scores.append(best_score)
            current_score = max(visible_scores, default=None)
            if current_score is not None and (
                best_score is None or current_score > best_score
            ):
                stagnation = 0
            else:
                stagnation += 1
            best_score = current_score
            best_score, stagnation = self._apply_producer_admissions(
                events_by_iteration.get(iteration, ()),
                active,
                records_by_id,
                best_score,
                stagnation,
                source_overrides=source_overrides,
                records=records,
            )

        visible_valid = [
            candidate
            for candidate in records
            if candidate.strategy == "population"
            and candidate.iteration <= current_iteration
            and candidate.evaluation.validity == 1
        ]
        best_candidate_id = (
            max(
                visible_valid,
                key=lambda candidate: candidate.evaluation.combined_score,
            ).candidate_id
            if visible_valid
            else None
        )
        return active, best_candidate_id, last_migration_iteration, stagnation

    def _validate_reconstructed_status(
        self,
        state: Mapping[str, Any],
        *,
        active: Mapping[int, Sequence[str]],
        best_candidate_id: str | None,
        stagnation: int,
    ) -> None:
        """Reject status values that contradict a deterministic modern checkpoint."""

        status = state.get("status")
        iteration = state.get("iteration")
        if status == "running":
            # A process can stop after the final running checkpoint is durable but before the
            # immediately following completed/stagnated state write. Resume may finish that
            # transition without replay.
            error = state.get("error")
            impossible_terminal_error = error in {
                "cancelled",
                "no valid candidate",
                "offspring_batch_failed",
            }
            empty_evaluator_failure = (
                iteration == 0
                and best_candidate_id is None
                and not any(active.values())
                and "outcome_schema_version" not in state
                and error in {"evaluator_timeout", "worker_unknown", "run_failed"}
            )
            if impossible_terminal_error or empty_evaluator_failure:
                raise EvolutionError("population state projection mismatch")
            return
        if status == "completed":
            valid = (
                iteration == self.config.max_rounds
                and stagnation < self.config.stagnation_rounds
                and best_candidate_id is not None
            )
        elif status == "stagnated":
            valid = (
                isinstance(iteration, int)
                and not isinstance(iteration, bool)
                and iteration > 0
                and stagnation >= self.config.stagnation_rounds
                and best_candidate_id is not None
            )
        elif status == "cancelled":
            valid = (
                isinstance(iteration, int)
                and not isinstance(iteration, bool)
                and iteration < self.config.max_rounds
                and state.get("error") == "cancelled"
            )
        elif status == "failed":
            failed_batch = (
                "failed_offspring_iteration" in state
                and "failed_offspring_sha256" in state
            )
            initialization_failure = (
                iteration == 0
                and best_candidate_id is None
                and not any(active.values())
                and "outcome_schema_version" not in state
                and state.get("error")
                in {
                    "candidate_failed",
                    "evaluator_timeout",
                    "worker_unknown",
                    "run_failed",
                }
            )
            exhausted_without_valid_candidate = (
                iteration == self.config.max_rounds
                and best_candidate_id is None
            )
            stagnated_without_valid_candidate = (
                isinstance(iteration, int)
                and not isinstance(iteration, bool)
                and iteration > 0
                and stagnation >= self.config.stagnation_rounds
                and best_candidate_id is None
            )
            valid = state.get("error") is not None and (
                failed_batch
                or initialization_failure
                or exhausted_without_valid_candidate
                or stagnated_without_valid_candidate
            )
        else:
            valid = False
        if not valid:
            raise EvolutionError("population state projection mismatch")

    def _active(self, state: dict[str, Any]) -> dict[int, list[str]]:
        if not state:
            return {i: [] for i in range(self.config.num_islands)}
        raw = state.get("active_ids", {})
        if not isinstance(raw, dict):
            raise EvolutionError("population state active_ids must contain string arrays")
        expected_keys = {str(index) for index in range(self.config.num_islands)}
        if set(raw) != expected_keys:
            raise EvolutionError("population state active_ids must contain every island")
        active: dict[int, list[str]] = {}
        for i in range(self.config.num_islands):
            ids = raw.get(str(i), [])
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise EvolutionError("population state active_ids must contain string arrays")
            active[i] = list(ids)
        PopulationState(
            iteration=int(state.get("iteration", 0)),
            population_size=self.config.population_size,
            offspring_per_iteration=self.config.offspring_per_iteration,
            num_islands=self.config.num_islands,
            active_ids={str(i): tuple(ids) for i, ids in active.items()},
            best_candidate_id=state.get("best_candidate_id"),
            rng_seed=self.config.rng_seed,
            last_migration_iteration=int(state.get("last_migration_iteration", 0)),
        )
        records_by_id = {
            candidate.candidate_id: candidate for candidate in self.archive.records()
        }
        if any(
            candidate_id not in records_by_id
            for ids in active.values()
            for candidate_id in ids
        ):
            raise EvolutionError("population state references an unknown candidate")
        if any(
            records_by_id[candidate_id].evaluation.validity != 1
            for ids in active.values()
            for candidate_id in ids
        ):
            raise EvolutionError("population state references an invalid candidate")
        best_candidate_id = state.get("best_candidate_id")
        if best_candidate_id is not None and (
            best_candidate_id not in records_by_id
            or records_by_id[best_candidate_id].evaluation.validity != 1
        ):
            raise EvolutionError("population state best candidate is invalid")
        if "seed_admission" in state and not any(active.values()):
            # Preserve the established seed-specific failure reported by the caller immediately
            # after this parser; it is already terminal and runs before seed re-evaluation.
            return active
        if state.get("candidate_integrity_schema_version") == CANDIDATE_INTEGRITY_SCHEMA_VERSION:
            pending = self._pending_offspring(state)
            if pending is not None:
                completed = sum(
                    item.iteration == pending[0]
                    for item in self.archive.offspring_outcomes()
                )
                if completed < pending[1]:
                    # The existing incomplete-batch gate owns this state and fails before any
                    # callback. Avoid reading baseline source files for rank reconstruction until
                    # the integrity validator has admitted the complete archive prefix.
                    return active
            if state.get("schema_version") != "1":
                raise EvolutionError("population state projection mismatch")
            expected_active, expected_best, expected_migration, expected_stagnation = (
                self._reconstruct_population_projection(state, tuple(records_by_id.values()))
            )
            required_projection = {
                "best_candidate_id",
                "rng_seed",
                "last_migration_iteration",
                "stagnation",
            }
            if not required_projection <= set(state):
                raise EvolutionError("population state projection mismatch")
            stored_rng_seed = state["rng_seed"]
            stored_migration = state["last_migration_iteration"]
            stored_stagnation = state["stagnation"]
            if (
                active != expected_active
                or best_candidate_id != expected_best
                or type(stored_rng_seed) is not type(self.config.rng_seed)
                or stored_rng_seed != self.config.rng_seed
                or type(stored_migration) is not int
                or stored_migration != expected_migration
                or type(stored_stagnation) is not int
                or stored_stagnation != expected_stagnation
            ):
                raise EvolutionError("population state projection mismatch")
            self._validate_reconstructed_status(
                state,
                active=active,
                best_candidate_id=expected_best,
                stagnation=expected_stagnation,
            )
        return active

    def _candidates(
        self,
        ids: Iterable[str],
        *,
        records: Sequence[Candidate] | None = None,
    ) -> list[Candidate]:
        by_id = {
            candidate.candidate_id: candidate
            for candidate in (records if records is not None else self.archive.records())
        }
        return [by_id[item] for item in ids if item in by_id]

    def _rank(
        self,
        candidates: list[Candidate],
        all_active: list[Candidate],
        *,
        source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
    ) -> list[Candidate]:
        return sorted(
            candidates,
            key=lambda item: (
                item.evaluation.validity,
                item.evaluation.combined_score,
                _novelty(
                    item,
                    [peer for peer in all_active if peer.candidate_id != item.candidate_id],
                    self.context.workspace,
                    source_overrides,
                ),
                item.candidate_id,
            ),
            reverse=True,
        )

    def _candidate_family(self, candidate: Candidate) -> str | None:
        """Project one exact canonical family tag from bounded experiment metadata."""
        if not isinstance(candidate.metadata, dict):
            return None
        experiment = candidate.metadata.get("experiment")
        if not isinstance(experiment, dict):
            return None
        change_tags = experiment.get("change_tags")
        if not isinstance(change_tags, list):
            return None
        repertoire = ALGORITHM_FAMILY_REPERTOIRES.get(self.context.contract.problem_type, ())
        return next(
            (
                family
                for family in repertoire
                if any(isinstance(tag, str) and tag == family for tag in change_tags)
            ),
            None,
        )

    def _family_elites(
        self,
        candidates: list[Candidate],
        all_active: list[Candidate],
        *,
        source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
    ) -> list[Candidate]:
        """Return the best valid candidate for every recognized family."""
        ranked = self._rank(candidates, all_active, source_overrides=source_overrides)
        elites: list[Candidate] = []
        seen: set[str] = set()
        for candidate in ranked:
            if candidate.evaluation.validity != 1:
                continue
            family = self._candidate_family(candidate)
            if family is None or family in seen:
                continue
            seen.add(family)
            elites.append(candidate)
        return elites

    def _trim(
        self,
        active: dict[int, list[str]],
        *,
        source_overrides: Mapping[str, Mapping[str, bytes]] | None = None,
        records: Sequence[Candidate] | None = None,
    ) -> None:
        all_active = self._candidates(
            (item for ids in active.values() for item in ids), records=records
        )
        for island in range(self.config.num_islands):
            candidates = self._candidates(active[island], records=records)
            ranked = self._rank(candidates, all_active, source_overrides=source_overrides)
            capacity = self._capacity(island)
            selected: list[Candidate] = []
            selected_ids: set[str] = set()

            valid = [candidate for candidate in ranked if candidate.evaluation.validity == 1]
            if valid:
                selected.append(valid[0])
                selected_ids.add(valid[0].candidate_id)
            for elite in self._family_elites(
                candidates, all_active, source_overrides=source_overrides,
            ):
                if len(selected) >= capacity:
                    break
                if elite.candidate_id not in selected_ids:
                    selected.append(elite)
                    selected_ids.add(elite.candidate_id)
            for candidate in valid:
                if len(selected) >= capacity:
                    break
                if candidate.candidate_id not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(candidate.candidate_id)
            active[island] = [item.candidate_id for item in selected]

    def _parent_pool(self, active: dict[int, list[str]], island: int) -> list[Candidate]:
        all_active = self._candidates(item for ids in active.values() for item in ids)
        candidates = self._candidates(active[island]) or all_active
        ranked = self._rank(candidates, all_active)
        elites = self._family_elites(candidates, all_active)
        if not elites:
            return ranked[:3]
        valid_ranked = [candidate for candidate in ranked if candidate.evaluation.validity == 1]
        selected = list(elites)
        selected_ids = {candidate.candidate_id for candidate in selected}
        selected.extend(
            candidate
            for candidate in valid_ranked
            if candidate.candidate_id not in selected_ids
        )
        return selected[:3]

    def _select_parent(self, active: dict[int, list[str]], island: int) -> Candidate | None:
        pool = self._parent_pool(active, island)
        if not pool:
            return None
        return self.rng.choice(pool)

    def _inspirations(self, active: dict[int, list[str]], island: int, parent: Candidate | None) -> tuple[Candidate, ...]:
        candidates = [
            item
            for other in range(self.config.num_islands)
            if other != island
            for item in self._candidates(active[other])
            if parent is None or item.candidate_id != parent.candidate_id
        ]
        if not candidates:
            candidates = [
                item
                for item in self._candidates(item for ids in active.values() for item in ids)
                if parent is None or item.candidate_id != parent.candidate_id
            ]
        valid = [candidate for candidate in candidates if candidate.evaluation.validity == 1]
        remaining = valid or candidates
        parent_family = self._candidate_family(parent) if parent is not None else None
        selected: list[Candidate] = []
        selected_families: set[str] = set()

        while remaining and len(selected) < 2:
            ranked = sorted(
                remaining,
                key=lambda item: (
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) != parent_family
                    and self._candidate_family(item) not in selected_families,
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) != parent_family,
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) not in selected_families,
                    _novelty(
                        item,
                        tuple(([parent] if parent else []) + selected),
                        self.context.workspace,
                    ),
                    item.evaluation.combined_score,
                    item.candidate_id,
                ),
                reverse=True,
            )
            chosen = ranked[0]
            selected.append(chosen)
            family = self._candidate_family(chosen)
            if family is not None:
                selected_families.add(family)
            remaining = [
                candidate
                for candidate in remaining
                if candidate.candidate_id != chosen.candidate_id
            ]
        return tuple(selected)

    @staticmethod
    def _pending_offspring(state: dict[str, Any]) -> tuple[int, int] | None:
        value = state.get("pending_offspring")
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "iteration",
            "attempt_count",
        }:
            raise EvolutionError("population_pending_batch_invalid")
        iteration = value["iteration"]
        attempt_count = value["attempt_count"]
        if (
            value["schema_version"] != "1"
            or isinstance(iteration, bool)
            or not isinstance(iteration, int)
            or iteration < 1
            or isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or not 1 <= attempt_count <= 256
        ):
            raise EvolutionError("population_pending_batch_invalid")
        return iteration, attempt_count

    def _validate_outcome_history(
        self,
        state: dict[str, Any],
        *,
        records: Sequence[Candidate] | None = None,
        outcomes: Sequence[OffspringOutcome] | None = None,
    ) -> None:
        if outcomes is None:
            validated_outcomes = tuple(self.archive.offspring_outcomes())
        else:
            validated_outcomes = tuple(outcomes)
            if any(not isinstance(item, OffspringOutcome) for item in validated_outcomes):
                raise EvolutionError("population_outcome_state_mismatch")
        if records is None:
            validated_records = tuple(self.archive.records())
        else:
            validated_records = tuple(records)
            if any(not isinstance(candidate, Candidate) for candidate in validated_records):
                raise EvolutionError("population_outcome_state_mismatch")
        if any(candidate.strategy != "population" for candidate in validated_records):
            raise EvolutionError("population_outcome_state_mismatch")
        producer_ids = self._producer_admission_ids(state, validated_records)
        pending = self._pending_offspring(state)
        failed_iteration = state.get("failed_offspring_iteration")
        failed_digest = state.get("failed_offspring_sha256")

        binding_fields = {
            "outcome_schema_version",
            "outcome_start_iteration",
            "outcome_watermark",
            "outcome_watermark_sha256",
            "outcome_archive_baseline_sha256",
        }
        present_binding_fields = binding_fields.intersection(state)
        if not present_binding_fields:
            current_iteration = state.get("iteration", 0)
            modern_integrity_state = (
                state.get("candidate_integrity_schema_version")
                == CANDIDATE_INTEGRITY_SCHEMA_VERSION
            )
            modern_binding_required = modern_integrity_state and (
                "seed_admission" in state
                or (
                    isinstance(current_iteration, int)
                    and not isinstance(current_iteration, bool)
                    and current_iteration > 0
                )
                or any(candidate.iteration > 0 for candidate in validated_records)
                or state.get("status") in {"completed", "stagnated"}
                or (
                    state.get("status") == "failed"
                    and state.get("error") == "offspring_batch_failed"
                )
            )
            if (
                validated_outcomes
                or pending is not None
                or failed_iteration is not None
                or failed_digest is not None
                or modern_binding_required
                or isinstance(current_iteration, bool)
                or not isinstance(current_iteration, int)
                or current_iteration < 0
                or any(candidate.iteration > current_iteration for candidate in validated_records)
            ):
                raise EvolutionError("population_outcome_state_mismatch")
            # Population states written before the outcome journal was introduced remain
            # resumable. The first new batch establishes a baseline at the next iteration.
            return
        if present_binding_fields != binding_fields:
            raise EvolutionError("population_outcome_state_mismatch")

        current_iteration = state.get("iteration", 0)
        start_iteration = state["outcome_start_iteration"]
        watermark = state["outcome_watermark"]
        watermark_digest = state["outcome_watermark_sha256"]
        baseline_digest = state["outcome_archive_baseline_sha256"]
        if (
            state["outcome_schema_version"] != "1"
            or isinstance(current_iteration, bool)
            or not isinstance(current_iteration, int)
            or current_iteration < 0
            or isinstance(start_iteration, bool)
            or not isinstance(start_iteration, int)
            or start_iteration < 1
            or isinstance(watermark, bool)
            or not isinstance(watermark, int)
            or watermark != current_iteration
            or start_iteration > watermark + 1
            or not isinstance(watermark_digest, str)
            or not _SHA256.fullmatch(watermark_digest)
            or not isinstance(baseline_digest, str)
            or not _SHA256.fullmatch(baseline_digest)
        ):
            raise EvolutionError("population_outcome_state_mismatch")

        if failed_iteration is not None and (
            isinstance(failed_iteration, bool)
            or not isinstance(failed_iteration, int)
            or state.get("status") != "failed"
            or failed_iteration != current_iteration + 1
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if (failed_iteration is None) != (failed_digest is None) or (
            failed_digest is not None
            and (
                not isinstance(failed_digest, str)
                or not _SHA256.fullmatch(failed_digest)
            )
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if pending is not None and (
            state.get("status") != "running"
            or failed_iteration is not None
            or pending[0] != current_iteration + 1
            or pending[1] != self.config.offspring_per_iteration
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if (
            start_iteration == watermark + 1
            and pending is None
            and failed_iteration is None
        ):
            raise EvolutionError("population_outcome_state_mismatch")

        grouped: dict[int, list[OffspringOutcome]] = {}
        for outcome in validated_outcomes:
            if (
                outcome.iteration < start_iteration
                or outcome.attempt >= self.config.offspring_per_iteration
                or outcome.island_id != outcome.attempt % self.config.num_islands
            ):
                raise EvolutionError("population_outcome_state_mismatch")
            grouped.setdefault(outcome.iteration, []).append(outcome)

        expected_attempts = set(range(self.config.offspring_per_iteration))
        for iteration in range(start_iteration, watermark + 1):
            completed = grouped.get(iteration, [])
            if (
                {item.attempt for item in completed} != expected_attempts
                or not any(item.code == "evaluated" for item in completed)
            ):
                raise EvolutionError("population_outcome_state_mismatch")

        completed_prefix = [
            item
            for item in validated_outcomes
            if start_iteration <= item.iteration <= watermark
        ]
        if self._outcome_digest(completed_prefix) != watermark_digest:
            raise EvolutionError("population_outcome_state_mismatch")
        baseline = [
            candidate
            for candidate in validated_records
            if candidate.iteration < start_iteration
            and candidate.candidate_id not in producer_ids
        ]
        if self._candidate_digest(baseline) != baseline_digest:
            raise EvolutionError("population_outcome_state_mismatch")

        future_iteration = current_iteration + 1
        for iteration, iteration_outcomes in grouped.items():
            if iteration <= watermark:
                continue
            attempts = {item.attempt for item in iteration_outcomes}
            if pending is not None and iteration == future_iteration:
                if not attempts <= expected_attempts:
                    raise EvolutionError("population_outcome_state_mismatch")
                continue
            if failed_iteration == iteration == future_iteration:
                if attempts != expected_attempts or any(
                    item.code == "evaluated" for item in iteration_outcomes
                ):
                    raise EvolutionError("population_outcome_state_mismatch")
                continue
            raise EvolutionError("population_outcome_state_mismatch")

        if failed_iteration is not None:
            failed_outcomes = grouped.get(failed_iteration, [])
            if (
                {item.attempt for item in failed_outcomes} != expected_attempts
                or any(item.code == "evaluated" for item in failed_outcomes)
                or self._outcome_digest(failed_outcomes) != failed_digest
            ):
                raise EvolutionError("population_outcome_state_mismatch")

        candidates_by_id = {item.candidate_id: item for item in validated_records}
        evaluated = [item for item in validated_outcomes if item.code == "evaluated"]
        evaluated_ids = [item.candidate_id for item in evaluated]
        if len(evaluated_ids) != len(set(evaluated_ids)):
            raise EvolutionError("population_outcome_state_mismatch")
        for outcome in evaluated:
            candidate_id = outcome.candidate_id
            assert candidate_id is not None
            candidate = candidates_by_id.get(candidate_id)
            if (
                candidate is None
                or candidate.strategy != "population"
                or candidate.iteration != outcome.iteration
                or candidate.island_id != outcome.island_id
            ):
                raise EvolutionError("population_outcome_state_mismatch")
        evaluated_id_set = set(evaluated_ids)
        if any(
            candidate.strategy == "population"
            and candidate.iteration >= start_iteration
            and candidate.candidate_id not in evaluated_id_set
            for candidate in validated_records
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        for iteration, iteration_outcomes in grouped.items():
            expected_ids = [
                item.candidate_id
                for item in sorted(iteration_outcomes, key=lambda item: item.attempt)
                if item.code == "evaluated"
            ]
            archived_ids = [
                candidate.candidate_id
                for candidate in validated_records
                if candidate.iteration == iteration
            ]
            if archived_ids != expected_ids:
                raise EvolutionError("population_outcome_state_mismatch")

    def _begin_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> dict[str, Any]:
        self._validate_outcome_history(state)
        if self._pending_offspring(state) is not None:
            raise EvolutionError("population_pending_batch_invalid")
        target_iteration = int(state.get("iteration", 0)) + 1
        if any(
            item.iteration == target_iteration
            for item in self.archive.offspring_outcomes()
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        records = self.archive.records()
        start_iteration = state.get("outcome_start_iteration", target_iteration)
        watermark_digest = state.get(
            "outcome_watermark_sha256", self._outcome_digest(())
        )
        baseline_digest = state.get(
            "outcome_archive_baseline_sha256",
            self._candidate_digest(
                candidate
                for candidate in records
                if candidate.iteration < start_iteration
                and candidate.candidate_id
                not in self._producer_admission_ids(state, records)
            ),
        )
        current = self.archive.best()
        self._state(
            "running",
            target_iteration - 1,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=int(state.get("stagnation", 0)),
            error=None,
            best_candidate_id=current.candidate_id if current else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=int(state.get("last_migration_iteration", 0)),
            pending_offspring={
                "schema_version": "1",
                "iteration": target_iteration,
                "attempt_count": self.config.offspring_per_iteration,
            },
            outcome_schema_version="1",
            outcome_start_iteration=start_iteration,
            outcome_watermark=target_iteration - 1,
            outcome_watermark_sha256=watermark_digest,
            outcome_archive_baseline_sha256=baseline_digest,
        )
        return self.archive.read_state()

    def _attempt_offspring(
        self,
        active: dict[int, list[str]],
        *,
        iteration: int,
        attempt: int,
    ) -> OffspringOutcome:
        island = attempt % self.config.num_islands
        try:
            selected_parent = self._select_parent(active, island)
            selected_inspirations = self._inspirations(active, island, selected_parent)
            request = GenerationRequest(
                iteration=iteration,
                parent=self._generation_candidate(selected_parent),
                inspirations=tuple(
                    self._generation_candidate(item) for item in selected_inspirations
                ),
                archive=self._generation_records(),
                workspace=self.context.workspace,
                candidate_id=self.archive.next_id(),
            )
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception:  # noqa: BLE001 - no narrower attempt result exists yet
            return OffspringOutcome(iteration, attempt, island, "run_failed")

        try:
            draft = _drafts(self.context.generate(request))[0]
            self._check_stage("candidate_generation")
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception:  # noqa: BLE001 - generator prose must not enter durable state
            return OffspringOutcome(iteration, attempt, island, "candidate_failed")

        try:
            candidate = self._persist(
                draft,
                iteration=iteration,
                generation=(selected_parent.generation + 1 if selected_parent else 0),
                parent=selected_parent,
                island_id=island,
            )
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled, _CandidateArchivePublicationUnknown):
            raise
        except _InitialCandidateFailure as exc:
            return OffspringOutcome(iteration, attempt, island, exc.code)
        except Exception:  # noqa: BLE001 - persistence failure is controlled and prose-free
            return OffspringOutcome(iteration, attempt, island, "candidate_failed")
        return OffspringOutcome(
            iteration,
            attempt,
            island,
            "evaluated",
            candidate_id=candidate.candidate_id,
        )

    def _finish_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> tuple[dict[str, Any], dict[int, list[str]]]:
        self._validate_outcome_history(state)
        pending = self._pending_offspring(state)
        if pending is None:
            raise EvolutionError("population_pending_batch_invalid")
        target_iteration, attempt_count = pending
        outcomes = sorted(
            (
                item
                for item in self.archive.offspring_outcomes()
                if item.iteration == target_iteration
            ),
            key=lambda item: item.attempt,
        )
        if len(outcomes) != attempt_count or [item.attempt for item in outcomes] != list(
            range(attempt_count)
        ):
            raise EvolutionError("population_iteration_incomplete")

        current_iteration = int(state.get("iteration", 0))
        records = self.archive.records()
        by_id = {candidate.candidate_id: candidate for candidate in records}
        evaluated = [item for item in outcomes if item.code == "evaluated"]
        evaluated_ids = [item.candidate_id for item in evaluated]
        if len(evaluated_ids) != len(set(evaluated_ids)) or any(
            candidate_id not in by_id
            or by_id[candidate_id].strategy != "population"
            or by_id[candidate_id].iteration != target_iteration
            or by_id[candidate_id].island_id != outcome.island_id
            for outcome, candidate_id in zip(evaluated, evaluated_ids, strict=True)
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        current_batch_candidates = {
            candidate.candidate_id
            for candidate in records
            if candidate.strategy == "population"
            and candidate.iteration > current_iteration
        }
        if current_batch_candidates != set(evaluated_ids):
            raise EvolutionError("population_outcome_state_mismatch")

        migration_watermark = int(state.get("last_migration_iteration", 0))
        if not evaluated:
            current = self.archive.best()
            self._state(
                "failed",
                current_iteration,
                active_ids={str(key): value for key, value in active.items()},
                stagnation=int(state.get("stagnation", 0)),
                error="offspring_batch_failed",
                best_candidate_id=current.candidate_id if current else None,
                rng_seed=self.config.rng_seed,
                last_migration_iteration=migration_watermark,
                outcome_schema_version="1",
                outcome_start_iteration=state["outcome_start_iteration"],
                outcome_watermark=current_iteration,
                outcome_watermark_sha256=state["outcome_watermark_sha256"],
                outcome_archive_baseline_sha256=state[
                    "outcome_archive_baseline_sha256"
                ],
                failed_offspring_iteration=target_iteration,
                failed_offspring_sha256=self._outcome_digest(outcomes),
            )
            return self.archive.read_state(), active

        previous_valid = [
            candidate
            for candidate in records
            if candidate.iteration <= current_iteration and candidate.evaluation.validity == 1
        ]
        previous_best_score = max(
            (candidate.evaluation.combined_score for candidate in previous_valid),
            default=None,
        )
        for outcome in evaluated:
            candidate_id = outcome.candidate_id
            assert candidate_id is not None
            if candidate_id in {item for ids in active.values() for item in ids}:
                raise EvolutionError("population_outcome_state_mismatch")
            active[outcome.island_id].append(candidate_id)
        self._trim(active)
        if self._migrate(active, target_iteration):
            migration_watermark = target_iteration
        current = self.archive.best()
        current_score = current.evaluation.combined_score if current else None
        stagnation = int(state.get("stagnation", 0))
        if current_score is not None and (
            previous_best_score is None or current_score > previous_best_score
        ):
            stagnation = 0
        else:
            stagnation += 1
        self._state(
            "running",
            target_iteration,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=stagnation,
            error=(
                None
                if len(evaluated) == len(outcomes)
                else "offspring_attempt_failed"
            ),
            best_candidate_id=current.candidate_id if current else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
            outcome_schema_version="1",
            outcome_start_iteration=state["outcome_start_iteration"],
            outcome_watermark=target_iteration,
            outcome_watermark_sha256=self._outcome_digest(
                item
                for item in self.archive.offspring_outcomes()
                if state["outcome_start_iteration"]
                <= item.iteration
                <= target_iteration
            ),
            outcome_archive_baseline_sha256=state[
                "outcome_archive_baseline_sha256"
            ],
        )
        return self.archive.read_state(), active

    def _resume_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> tuple[dict[str, Any], dict[int, list[str]]]:
        self._validate_outcome_history(state)
        pending = self._pending_offspring(state)
        if pending is None:
            return state, active
        completed = sum(
            item.iteration == pending[0]
            for item in self.archive.offspring_outcomes()
        )
        if completed != pending[1]:
            raise EvolutionError("population_iteration_incomplete")
        return self._finish_offspring_batch(state, active)

    def _migrate(self, active: dict[int, list[str]], iteration: int) -> bool:
        if self.config.num_islands <= 1 or not self.config.migration_interval:
            return False
        if iteration % self.config.migration_interval or self.config.migration_rate <= 0:
            return False
        count = max(1, int(self._capacity(0) * self.config.migration_rate))
        moves: list[tuple[int, int, str]] = []
        for source in range(self.config.num_islands):
            candidates = self._rank(self._candidates(active[source]), self._candidates(item for ids in active.values() for item in ids))
            for candidate in candidates[:count]:
                if len(active[source]) > 1:
                    moves.append((source, (source + 1) % self.config.num_islands, candidate.candidate_id))
        for source, target, candidate_id in moves:
            for ids in active.values():
                while candidate_id in ids:
                    ids.remove(candidate_id)
            active[target].append(candidate_id)
        self._trim(active)
        return bool(moves)

    def _validate_ordinary_resume_evidence(self, state: dict[str, Any]) -> None:
        """Validate ordinary state, journal, and candidates without invoking seed admission."""

        # Recognize a legacy ordinary archive before the outcome journal so historical files
        # receive the fixed migration error even when their old watermark no longer describes the
        # new archive representation.
        records = self.archive.records()
        if any(
            candidate.strategy == "population"
            and (
                candidate.source_sha256 is None
                or candidate.receipt_sha256 is None
                or candidate.integrity is None
            )
            for candidate in records
        ):
            self._validate_candidate_integrity_state(state)
        # Validate the append-only offspring journal first.  This preserves its established
        # failure codes for incomplete/tampered batches; candidate sidecars are checked immediately
        # afterwards, before any generator or evaluator callback can run.
        self._validate_outcome_history(state)
        self._validate_candidate_integrity_state(
            state,
            outcome_history_validated=True,
        )

    def validate_ordinary_resume_integrity(self) -> None:
        """Check existing ordinary evidence without generating, evaluating, or admitting seeds.

        Controller integrations use this narrow preflight before a supplied seed manifest is
        locally re-evaluated on resume.  Seed receipts retain their separate admission gate.
        """

        state = self._load_state()
        self._validate_ordinary_resume_evidence(state)
        active = self._active(state)
        if "seed_admission" in state and not any(active.values()):
            raise EvolutionError("verified_seed_active_population_missing")
        pending = self._pending_offspring(state)
        if pending is None:
            return
        completed = sum(
            item.iteration == pending[0]
            for item in self.archive.offspring_outcomes()
        )
        if completed != pending[1]:
            # Seed re-admission invokes the evaluator, so an incomplete ordinary batch must stop
            # at this read-only preflight rather than waiting for the later resume path.
            raise EvolutionError("population_iteration_incomplete")

        # Validate the remaining nonmutating completion invariants as well.  The real resume keeps
        # ownership of ranking, migration, and the final state write.
        target_iteration, attempt_count = pending
        outcomes = sorted(
            (
                item
                for item in self.archive.offspring_outcomes()
                if item.iteration == target_iteration
            ),
            key=lambda item: item.attempt,
        )
        if len(outcomes) != attempt_count or [item.attempt for item in outcomes] != list(
            range(attempt_count)
        ):
            raise EvolutionError("population_iteration_incomplete")
        records = self.archive.records()
        by_id = {candidate.candidate_id: candidate for candidate in records}
        evaluated = [item for item in outcomes if item.code == "evaluated"]
        evaluated_ids = [item.candidate_id for item in evaluated]
        current_iteration = int(state.get("iteration", 0))
        if len(evaluated_ids) != len(set(evaluated_ids)) or any(
            candidate_id not in by_id
            or by_id[candidate_id].strategy != "population"
            or by_id[candidate_id].iteration != target_iteration
            or by_id[candidate_id].island_id != outcome.island_id
            for outcome, candidate_id in zip(evaluated, evaluated_ids, strict=True)
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        current_batch_candidates = {
            candidate.candidate_id
            for candidate in records
            if candidate.strategy == "population"
            and candidate.iteration > current_iteration
        }
        active_ids = {item for ids in active.values() for item in ids}
        if current_batch_candidates != set(evaluated_ids) or any(
            candidate_id in active_ids for candidate_id in evaluated_ids
        ):
            raise EvolutionError("population_outcome_state_mismatch")

    def run(self) -> StrategyResult:
        self.archive._require_writable()
        if self.context.bundle_pipeline is None and any(
            candidate.bundle_evidence is not None for candidate in self.archive.records()
        ):
            raise EvolutionError("bundle_candidate_pipeline_required")
        state = self._seed_resume_gate(self._load_state())
        self._validate_ordinary_resume_evidence(state)
        active = self._active(state)
        if "seed_admission" in state and not any(active.values()):
            raise EvolutionError("verified_seed_active_population_missing")
        state, active = self._resume_offspring_batch(state, active)
        terminal = self._terminal(state)
        if terminal:
            return terminal
        iteration = int(state.get("iteration", 0))
        stagnation = int(state.get("stagnation", 0))
        migration_watermark = int(state.get("last_migration_iteration", 0))
        error: str | None = state.get("error")
        if not any(active.values()):
            existing = self.archive.records()
            if existing:
                eligible = [
                    candidate
                    for candidate in existing
                    if candidate.evaluation.validity == 1
                ]
                for index, candidate in enumerate(eligible[-self.config.population_size :]):
                    active[index % self.config.num_islands].append(candidate.candidate_id)
            else:
                initialization_error: str | None = None
                evaluator_failure: str | None = None
                for index in range(self.config.population_size):
                    self._check_stage("candidate_generation")
                    if self._cancelled():
                        self._trim(active)
                        current = self.archive.best()
                        self._state(
                            "cancelled",
                            iteration,
                            active_ids={str(k): v for k, v in active.items()},
                            stagnation=stagnation,
                            error="cancelled",
                            best_candidate_id=(
                                current.candidate_id if current else None
                            ),
                            rng_seed=self.config.rng_seed,
                            last_migration_iteration=migration_watermark,
                        )
                        return self.archive.result(self.name, "cancelled", iteration, "cancelled")
                    request = GenerationRequest(
                        iteration=0,
                        parent=None,
                        inspirations=(),
                        archive=self._generation_records(),
                        workspace=self.context.workspace,
                        candidate_id=self.archive.next_id(),
                    )
                    try:
                        drafts = _drafts(self.context.generate(request))
                        self._check_stage("candidate_generation")
                        draft = drafts[0]
                        candidate = self._persist(draft, iteration=0, generation=0, parent=None, island_id=index % self.config.num_islands)
                        if candidate.evaluation.validity == 1:
                            active[index % self.config.num_islands].append(
                                candidate.candidate_id
                            )
                    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
                        raise
                    except _CandidateArchivePublicationUnknown:
                        raise
                    except _InitialCandidateFailure as exc:
                        # Keep only the fixed evaluator outcome; the exception chain may contain
                        # provider or credential text and must never cross the durable boundary.
                        if evaluator_failure is None:
                            evaluator_failure = exc.code
                        if initialization_error is None:
                            initialization_error = exc.code
                        error = initialization_error
                    except Exception:  # noqa: BLE001 - initialization retains one fixed code
                        if initialization_error is None:
                            initialization_error = "candidate_failed"
                        error = initialization_error
                self._trim(active)
                if not any(active.values()) and evaluator_failure is not None:
                    terminal_error = evaluator_failure
                    self._state(
                        "failed",
                        iteration,
                        active_ids={str(k): v for k, v in active.items()},
                        stagnation=0,
                        error=terminal_error,
                        best_candidate_id=None,
                        rng_seed=self.config.rng_seed,
                        last_migration_iteration=migration_watermark,
                    )
                    return self.archive.result(
                        self.name, "failed", iteration, terminal_error
                    )
        initial_best = self.archive.best()
        self._state(
            "running",
            iteration,
            active_ids={str(k): v for k, v in active.items()},
            stagnation=stagnation,
            error=error,
            best_candidate_id=initial_best.candidate_id if initial_best else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
        )
        state = self.archive.read_state()
        if iteration > 0 and stagnation >= self.config.stagnation_rounds:
            current = self.archive.best()
            terminal_status = "stagnated" if current is not None else "failed"
            terminal_error = error or (
                "no valid candidate" if terminal_status == "failed" else None
            )
            self._state(
                terminal_status,
                iteration,
                active_ids={str(key): value for key, value in active.items()},
                stagnation=stagnation,
                error=terminal_error,
                best_candidate_id=current.candidate_id if current else None,
                rng_seed=self.config.rng_seed,
                last_migration_iteration=migration_watermark,
            )
            return self.archive.result(
                self.name,
                terminal_status,
                iteration,
                terminal_error,
            )

        while iteration < self.config.max_rounds:
            self._check_stage("selection")
            if self._cancelled():
                current = self.archive.best()
                self._state(
                    "cancelled",
                    iteration,
                    active_ids={str(k): v for k, v in active.items()},
                    stagnation=stagnation,
                    error="cancelled",
                    best_candidate_id=current.candidate_id if current else None,
                    rng_seed=self.config.rng_seed,
                    last_migration_iteration=migration_watermark,
                )
                return self.archive.result(self.name, "cancelled", iteration, "cancelled")
            state = self._begin_offspring_batch(state, active)
            target_iteration, _ = self._pending_offspring(state) or (iteration + 1, 0)
            for offset in range(self.config.offspring_per_iteration):
                self._check_stage("candidate_generation")
                outcome = self._attempt_offspring(
                    active,
                    iteration=target_iteration,
                    attempt=offset,
                )
                # If this append fails, pending intent remains canonical. Resume rejects the
                # incomplete batch and never repeats an attempt with uncertain terminal state.
                self.archive.append_offspring_outcome(outcome)
                self._check_stage("candidate_persistence")
                try:
                    self.context.observe("offspring_outcome", outcome.to_dict())
                except Exception as exc:  # noqa: BLE001 - optional audit sink
                    del exc
            state, active = self._finish_offspring_batch(state, active)
            self._check_stage("selection")
            terminal = self._terminal(state)
            if terminal:
                return terminal
            iteration = int(state["iteration"])
            stagnation = int(state.get("stagnation", 0))
            migration_watermark = int(state.get("last_migration_iteration", 0))
            error = state.get("error")
            current = self.archive.best()
            if stagnation >= self.config.stagnation_rounds:
                terminal_status = "stagnated" if current is not None else "failed"
                terminal_error = error or (
                    "no valid candidate" if terminal_status == "failed" else None
                )
                self._state(
                    terminal_status,
                    iteration,
                    active_ids={str(k): v for k, v in active.items()},
                    stagnation=stagnation,
                    error=terminal_error,
                    best_candidate_id=current.candidate_id if current else None,
                    rng_seed=self.config.rng_seed,
                    last_migration_iteration=migration_watermark,
                )
                return self.archive.result(
                    self.name,
                    terminal_status,
                    iteration,
                    terminal_error,
                )

        status = "completed" if self.archive.best() is not None else "failed"
        final_error = error or ("no valid candidate" if status == "failed" else None)
        final_best = self.archive.best()
        self._state(
            status,
            iteration,
            active_ids={str(k): v for k, v in active.items()},
            stagnation=stagnation,
            error=final_error,
            best_candidate_id=final_best.candidate_id if final_best else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
        )
        return self.archive.result(self.name, status, iteration, final_error)

    def resume(self) -> StrategyResult:
        return self.run()


class OpenEvolveStrategy(_BaseStrategy):
    """Run a local OpenEvolve producer and admit one result through the exact harness."""

    name: Literal["openevolve"] = "openevolve"

    def _budget(self) -> dict[str, Any]:
        return {
            "max_rounds": self.config.max_rounds,
            "stagnation_rounds": self.config.stagnation_rounds,
            "population_size": self.config.population_size,
            "offspring_per_iteration": self.config.offspring_per_iteration,
            "num_islands": self.config.num_islands,
            "migration_interval": self.config.migration_interval,
            "migration_rate": self.config.migration_rate,
            "rng_seed": self.config.rng_seed,
            "timeout_seconds": self.config.timeout_seconds,
        }

    def _producer_fingerprint(self) -> str:
        # Import lazily: the handoff adapter depends on the neutral CandidateDraft definitions in
        # this module, so a module-level import would create a cycle.
        from .openevolve_handoff import OPENEVOLVE_RESULT_PROTOCOL

        command_sha256 = self.config.to_dict().get("command_sha256")
        payload = {
            "schema_version": "1",
            "producer_id": "openevolve",
            "wrapper_protocol": OPENEVOLVE_RESULT_PROTOCOL,
            "command_sha256": command_sha256,
            "contract_sha256": self.context.contract.digest(),
            "budget": self._budget(),
        }
        return hashlib.sha256(_canonical_seed_bytes(payload)).hexdigest()

    @staticmethod
    def _stop_producer(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait()
        except OSError:
            pass

    def _run_producer(self, external: Path, config_path: Path) -> str:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [*self.config.command, str(config_path)],
                cwd=external,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + float(self.config.timeout_seconds)
            while True:
                if self._cancelled():
                    self._stop_producer(process)
                    return "cancelled"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_producer(process)
                    return "timed_out"
                try:
                    return "succeeded" if process.wait(timeout=min(0.1, remaining)) == 0 else "failed"
                except subprocess.TimeoutExpired:
                    continue
        except OSError:
            return "start_failed"
        finally:
            if process is not None and process.poll() is None:
                self._stop_producer(process)

    def _failed(self, code: str) -> StrategyResult:
        self._state("failed", 0, error=code)
        return self.archive.result(self.name, "failed", 0, code)

    def _observe_seed_commit(self, candidates: Sequence[Candidate]) -> None:
        for candidate in candidates:
            try:
                self.context.observe("candidate", candidate.to_dict())
            except Exception as exc:  # noqa: BLE001 - optional audit sink
                del exc
        state = self.archive.read_state()
        try:
            self.context.observe("state", state)
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc

    def _fresh_completed_admission(self, state: dict[str, Any]) -> None:
        """Re-evaluate canonical material without invoking the producer again."""

        from .openevolve_handoff import (
            declared_protocol_environment_sha256,
            source_only_dependency_sha256,
        )
        from .seed_handoff import SeedManifest, admit_seed_manifest

        try:
            records = self.archive.records()
            if len(records) != 1:
                raise EvolutionError("openevolve_resume_mismatch")
            candidate = records[0]
            if (
                candidate.strategy != "openevolve"
                or candidate.iteration != 1
                or candidate.generation != 0
                or candidate.parent_id is not None
                or candidate.island_id is not None
            ):
                raise EvolutionError("openevolve_resume_mismatch")
            candidate_root = self.archive.candidates_root / candidate.candidate_id
            source_path = _confined(
                self.archive.workspace,
                self.archive.workspace / candidate.code_path,
                "OpenEvolve canonical source",
            )
            _reject_symlink_components(
                source_path,
                self.archive.candidates_root,
                "OpenEvolve canonical source",
            )
            source_path.relative_to(candidate_root)
            record = self.archive._read_seed_json(source_path.parent / "record.json")
            evidence = record.get("seed_handoff_evidence")
            if not isinstance(evidence, dict) or set(evidence) != {
                "schema_version",
                "provenance",
                "external_evidence",
                "provenance_sha256",
                "handoff_sha256",
                "receipt_sha256",
            }:
                raise EvolutionError("openevolve_resume_mismatch")
            projection = evidence["provenance"]
            external_evidence = evidence["external_evidence"]
            handoff = candidate.metadata.get("seed_handoff")
            seed_metadata = candidate.metadata.get("seed_metadata")
            if (
                evidence["schema_version"] != "1"
                or not isinstance(projection, dict)
                or set(projection) != {
                    "origin_kind",
                    "producer_id",
                    "producer_fingerprint",
                    "producer_run_id",
                    "material_refs_sha256",
                    "external_evidence_sha256",
                }
                or projection["origin_kind"] != "external"
                or projection["producer_id"] != "openevolve"
                or projection["material_refs_sha256"] != _canonical_seed_sha256([])
                or not isinstance(external_evidence, dict)
                or projection["external_evidence_sha256"]
                != _canonical_seed_sha256(external_evidence)
                or not isinstance(handoff, dict)
                or not isinstance(seed_metadata, dict)
                or handoff.get("candidate_id") != candidate.candidate_id
                or not isinstance(handoff.get("lineage"), list)
            ):
                raise EvolutionError("openevolve_resume_mismatch")
            evaluator_fingerprint = self.config.evaluator_fingerprint
            if evaluator_fingerprint is None:
                raise EvolutionError("openevolve_resume_mismatch")
            source_sha256 = handoff.get("source_sha256")
            if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
                raise EvolutionError("openevolve_resume_mismatch")
            dependency_sha256 = source_only_dependency_sha256(source_sha256)
            environment_sha256 = declared_protocol_environment_sha256()
            manifest = SeedManifest.from_dict(
                {
                    "schema_version": "1",
                    "contract_sha256": self.context.contract.digest(),
                    "evaluator": {
                        "kind": "exact_harness",
                        "fingerprint": evaluator_fingerprint,
                    },
                    "dependency_sha256": dependency_sha256,
                    "environment_sha256": environment_sha256,
                    "seeds": [
                        {
                            "identity": candidate.candidate_id,
                            "source_path": source_path.name,
                            "source_sha256": source_sha256,
                            "lineage": handoff["lineage"],
                            "provenance": {
                                "origin_kind": "external",
                                "producer_id": "openevolve",
                                "producer_fingerprint": self._producer_fingerprint(),
                                "producer_run_id": projection["producer_run_id"],
                                "material_refs": [],
                                "external_evidence": external_evidence,
                            },
                            "metadata": seed_metadata,
                        }
                    ],
                },
                source_root=source_path.parent,
            )
            admission = admit_seed_manifest(
                manifest,
                self.context.contract,
                self.context.evaluate,
                evaluator_kind="exact_harness",
                evaluator_fingerprint=evaluator_fingerprint,
                dependency_sha256=dependency_sha256,
                environment_sha256=environment_sha256,
                num_islands=1,
            )
            self.archive.validate_initial_seeds(
                admission.admitted,
                state=state,
                contract_sha256=self.context.contract.digest(),
                evaluator_fingerprint=evaluator_fingerprint,
                canonical_strategy="openevolve",
            )
        except Exception as exc:
            if isinstance(exc, EvolutionError) and str(exc) == "openevolve_resume_mismatch":
                raise
            raise EvolutionError("openevolve_resume_mismatch") from exc

    def run(self) -> StrategyResult:
        self.archive._require_writable()
        # A producer launch is an external effect even though it uses a private temporary
        # directory. Validate any existing workspace identity before starting that process.
        self.archive._guard_active_write(self.name)
        state = self._load_state()
        if not state:
            # Admission publishes one atomic seed tree. Prove that the exact final commit shape is
            # currently possible before paying the irreversible cost of an external producer run.
            self.archive._preflight_seed_commit_root(self.context.contract.digest())
        if state.get("status") == "completed":
            if "seed_admission" not in state:
                raise EvolutionError("openevolve_resume_mismatch")
            self._fresh_completed_admission(state)
            return self.archive.result(self.name, "completed", 1)
        terminal = self._terminal(state)
        if terminal:
            return terminal
        # OpenEvolve publishes a completed seed tree atomically and never checkpoints a running
        # state. A non-terminal state cannot be committed by this path; do not launch its producer.
        if state:
            raise EvolutionError("openevolve_resume_mismatch")
        command = self.config.command
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            return self._failed("openevolve_command_invalid")
        if self._cancelled():
            self._state("cancelled", 0, error="cancelled")
            return self.archive.result(self.name, "cancelled", 0, "cancelled")
        evaluator_fingerprint = self.config.evaluator_fingerprint
        if evaluator_fingerprint is None:
            return self._failed("openevolve_evaluator_identity_missing")
        from .openevolve_handoff import OpenEvolveHandoffError, admit_openevolve_result
        from .seed_handoff import SeedAdmissionError

        try:
            with tempfile.TemporaryDirectory(prefix="lunar-openevolve-") as temporary:
                external = Path(temporary)
                os.chmod(external, 0o700)
                config_path = external / "config.json"
                config_payload = {
                    "schema_version": "1",
                    "contract": self.context.contract.to_dict(),
                    "workspace": str(external),
                    "result_path": "result.json",
                    "producer": {
                        "id": "openevolve",
                        "fingerprint": self._producer_fingerprint(),
                    },
                    "budget": self._budget(),
                }
                config_text = json.dumps(
                    config_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                if len(config_text.encode("utf-8")) > MAX_SOURCE_BYTES:
                    return self._failed("openevolve_config_too_large")
                descriptor = os.open(
                    config_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                )
                try:
                    content = memoryview(config_text.encode("utf-8"))
                    written = 0
                    while written < len(content):
                        written += os.write(descriptor, content[written:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                producer_status = self._run_producer(external, config_path)
                if producer_status == "cancelled":
                    self._state("cancelled", 0, error="cancelled")
                    return self.archive.result(self.name, "cancelled", 0, "cancelled")
                if producer_status != "succeeded":
                    return self._failed(f"openevolve_command_{producer_status}")

                admitted = admit_openevolve_result(
                    external,
                    self.context.contract,
                    self.context.evaluate,
                    evaluator_fingerprint=evaluator_fingerprint,
                    producer_fingerprint=self._producer_fingerprint(),
                    staging_root=external / "admission",
                    num_islands=1,
                )
        except OSError:
            return self._failed("openevolve_workspace_failed")
        except OpenEvolveHandoffError:
            return self._failed("openevolve_result_invalid")
        except SeedAdmissionError:
            return self._failed("openevolve_local_evaluation_failed")

        state_payload = self._state_payload(
            "completed",
            1,
            error=None,
            best_candidate_id=admitted.candidate_id,
        )
        candidates = self.archive.commit_initial_seeds(
            (admitted,),
            state=state_payload,
            contract_sha256=self.context.contract.digest(),
            evaluator_fingerprint=self.config.evaluator_fingerprint,
            canonical_strategy="openevolve",
        )
        self._observe_seed_commit(candidates)
        return self.archive.result(self.name, "completed", 1)

    def resume(self) -> StrategyResult:
        return self.run()


def build_strategy(context: EvolutionContext) -> EvolutionStrategy:
    """Construct the strategy selected by an explicit context configuration."""

    if context.contract.evolution.strategy == "loop":
        raise EvolutionError(LOOP_STRATEGY_RETIRED_MESSAGE)
    if context.config.strategy == "population":
        return PopulationStrategy(context)
    if context.config.strategy == "openevolve":
        return OpenEvolveStrategy(context)
    raise ValueError(f"unsupported evolution strategy: {context.config.strategy}")


def config_from_contract(
    contract: AlgorithmProblemContract,
    *,
    population_size: int = 8,
    offspring_per_iteration: int = 1,
    num_islands: int = 1,
    migration_interval: int = 0,
    migration_rate: float = 0.1,
    rng_seed: int | None = None,
    timeout_seconds: float = 900.0,
    command: Sequence[str] = (),
    generator_fingerprint: str | None = None,
    evaluator_fingerprint: str | None = None,
) -> EvolutionConfig:
    """Map the persisted Feature 012 evolution choice to executable strategy knobs."""

    return EvolutionConfig(
        strategy=contract.evolution.strategy,
        max_rounds=contract.evolution.max_rounds,
        stagnation_rounds=contract.evolution.stagnation_rounds,
        population_size=population_size,
        offspring_per_iteration=offspring_per_iteration,
        num_islands=num_islands,
        migration_interval=migration_interval,
        migration_rate=migration_rate,
        rng_seed=rng_seed,
        timeout_seconds=timeout_seconds,
        command=tuple(command),
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
    )


__all__ = [
    "AdmittedSeedInput",
    "Candidate",
    "CandidateArchive",
    "CandidateDraft",
    "CandidateEvaluator",
    "CandidateExecution",
    "CandidateGenerator",
    "CandidateInputArtifact",
    "CandidateIntegrityAuthority",
    "CandidateReceipt",
    "CandidateRunner",
    "CommandCandidateEvaluator",
    "CommandCandidateGenerator",
    "ContractCandidateRunner",
    "EvolutionConfig",
    "EvolutionContext",
    "EvolutionError",
    "EvolutionStrategy",
    "ExecutionAwareCandidateEvaluator",
    "GenerationRequest",
    "LoopStrategy",
    "OffspringOutcome",
    "OpenEvolveStrategy",
    "PopulationConfig",
    "PopulationState",
    "PopulationStrategy",
    "SeedEvidenceRecord",
    "StrategyResult",
    "WorkerUnknownError",
    "build_strategy",
    "config_from_contract",
    "contract_candidate_runner_fingerprint",
    "resolve_candidate_integrity_authority",
    "stage_candidate_inputs",
]
