"""Fail-closed staged publication for producer bundle batches.

This module consumes already adjudicated local evidence.  It never invokes a producer,
runner, evaluator, or campaign.  A complete batch is assembled below the system-derived
producer-batch directory first; the workspace marker then makes every intermediate state
fail closed to native archive readers.  The marker is removed only after the archive, state,
source trees, sidecars, and terminal journal have all been verified.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as _files
from .evolution import MAX_ARCHIVE_BYTES, MAX_ARCHIVE_LINE_BYTES, MAX_STATE_BYTES
from .producer_bundle_preflight import (
    ProducerBundlePreflightReceipt,
    _authority_digest,
    parse_producer_bundle_preflight_receipt,
)
from .producer_bundle_publication import (
    MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES,
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)

_PROTOCOL = "lunar-producer-bundle-publication-v1"
_SCHEMA_VERSION = "1"
_MARKER_NAME = "producer-publication.json"
_LOCK_NAME = "producer-publication.lock"
_STAGE_NAME = "stage"
_MAX_SOURCE_BYTES = 16 * 1024 * 1024


class ProducerBundlePublicationStagingError(ValueError):
    """Fixed-code failure at the staged publication boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundlePublicationStagingError(code)


def _canonical(value: object, maximum: int = MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_canonical_invalid") from exc
    if len(data) > maximum:
        _fail("producer_bundle_publication_too_large")
    return data


def _pretty(value: object, maximum: int) -> bytes:
    try:
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_canonical_invalid") from exc
    if len(data) > maximum:
        _fail("producer_bundle_publication_too_large")
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        _fail("producer_bundle_publication_path_invalid")


def _regular(path: Path, code: str = "producer_bundle_publication_path_invalid") -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError:
        _fail(code)
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
        _fail(code)
    return info


def _directory(path: Path, code: str = "producer_bundle_publication_path_invalid") -> None:
    try:
        info = os.lstat(path)
    except OSError:
        _fail(code)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        _fail(code)


def _read(path: Path, maximum: int) -> bytes:
    try:
        return _files.read_regular_file(_files.absolute_path(path), maximum)
    except Exception as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_evidence_invalid") from exc


def _safe_relative(value: object, code: str = "producer_bundle_publication_path_invalid") -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(code)
    path = Path(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        _fail(code)
    return value


def _confined(root: Path, relative: str, *, code: str = "producer_bundle_publication_path_invalid") -> Path:
    _safe_relative(relative, code)
    current = root
    for index, part in enumerate(Path(relative).parts):
        current = current / part
        if _present(current):
            try:
                info = os.lstat(current)
            except OSError:
                _fail(code)
            if stat.S_ISLNK(info.st_mode) or (index < len(Path(relative).parts) - 1 and not stat.S_ISDIR(info.st_mode)):
                _fail(code)
    return current


def _ensure_directory(root: Path, relative: str) -> Path:
    """Create a private, no-follow directory chain below ``root`` for nested source files."""
    _safe_relative(relative)
    current = root
    for part in Path(relative).parts:
        current = current / part
        if _present(current):
            _directory(current)
            continue
        try:
            current.mkdir(mode=0o700)
        except OSError as exc:
            raise ProducerBundlePublicationStagingError("producer_bundle_publication_stage_write_failed") from exc
        _fsync_dir(current.parent)
    return current


def _workspace(value: str | Path) -> Path:
    try:
        path = Path(value).expanduser().absolute()
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_workspace_invalid") from exc
    if path.is_symlink() or not path.is_dir():
        _fail("producer_bundle_publication_workspace_invalid")
    evolution = path / "evolution"
    _directory(evolution, "producer_bundle_publication_evolution_missing")
    _directory(evolution / "producer-batches", "producer_bundle_publication_batches_missing")
    return path


def _batch(workspace: Path, journal_id: str) -> Path:
    # journal IDs are validated by the journal DTO; reject any path interpretation anyway.
    _safe_relative(journal_id, "producer_bundle_publication_journal_id_invalid")
    path = workspace / "evolution" / "producer-batches" / journal_id
    _directory(path, "producer_bundle_publication_batch_missing")
    return path


def _write_new(path: Path, content: bytes, *, maximum: int) -> None:
    if len(content) > maximum:
        _fail("producer_bundle_publication_too_large")
    if _present(path):
        _fail("producer_bundle_publication_staging_conflict")
    _directory(path.parent)
    temporary = path.parent / ("." + path.name + ".tmp")
    if _present(temporary):
        _fail("producer_bundle_publication_staging_conflict")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("publication write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, path, follow_symlinks=False)
        os.unlink(temporary)
        _fsync_dir(path.parent)
    except ProducerBundlePublicationStagingError:
        raise
    except OSError as exc:
        try:
            if _present(temporary):
                temporary.unlink()
        except OSError:
            pass
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_stage_write_failed") from exc


def _replace_existing(path: Path, content: bytes, *, maximum: int) -> None:
    if len(content) > maximum:
        _fail("producer_bundle_publication_too_large")
    _regular(path)
    temporary = path.parent / ("." + path.name + ".replace.tmp")
    if _present(temporary):
        _fail("producer_bundle_publication_staging_conflict")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("publication write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except ProducerBundlePublicationStagingError:
        raise
    except OSError as exc:
        try:
            if _present(temporary):
                temporary.unlink()
        except OSError:
            pass
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_commit_unknown") from exc

def _replace_file(source: Path, target: Path) -> None:
    _regular(source)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        _fail("producer_bundle_publication_commit_conflict")
    try:
        os.replace(source, target)
        _fsync_dir(target.parent)
    except OSError as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_commit_unknown") from exc


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_sync_failed") from exc


@contextmanager
def _locked(workspace: Path):
    root = workspace / "evolution"
    lock = root / _LOCK_NAME
    if _present(lock):
        _regular(lock)
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("publication lock invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.lstat(lock)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise OSError("publication lock replaced")
        yield
    except ProducerBundlePublicationStagingError:
        raise
    except OSError as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_lock_failed") from exc
    finally:
        try:
            os.close(descriptor)
        except (UnboundLocalError, OSError):
            pass


@dataclass(frozen=True, slots=True)
class ProducerBundlePublicationArtifact:
    """Already verified candidate bytes and sidecars ready for native publication."""

    candidate_id: str
    source_files: Mapping[str, bytes | str]
    record: Mapping[str, object]
    receipt: Mapping[str, object]
    execution_receipt_sha256: str | None = None
    evaluation_receipt_sha256: str | None = None
    publication_receipt_sha256: str | None = None
    execution_receipt: Mapping[str, object] | None = None
    evaluation_receipt: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id:
            _fail("producer_bundle_publication_candidate_invalid")
        if not isinstance(self.source_files, Mapping) or not self.source_files:
            _fail("producer_bundle_publication_source_invalid")
        if not isinstance(self.record, Mapping) or not isinstance(self.receipt, Mapping):
            _fail("producer_bundle_publication_sidecar_invalid")
        for value, code in ((self.execution_receipt, "producer_bundle_publication_execution_receipt_invalid"),
                            (self.evaluation_receipt, "producer_bundle_publication_evaluation_receipt_invalid")):
            if value is not None and not isinstance(value, Mapping):
                _fail(code)
        for value, code in ((self.execution_receipt_sha256, "producer_bundle_publication_execution_receipt_invalid"),
                            (self.evaluation_receipt_sha256, "producer_bundle_publication_evaluation_receipt_invalid"),
                            (self.publication_receipt_sha256, "producer_bundle_publication_publication_receipt_invalid")):
            if value is not None and (not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
                _fail(code)
        for name, content in self.source_files.items():
            _safe_relative(name, "producer_bundle_publication_source_path_invalid")
            if name in {"record.json", "receipt.json", "execution-receipt.json", "evaluation-receipt.json"}:
                _fail("producer_bundle_publication_source_path_invalid")
            if isinstance(content, str):
                encoded = content.encode("utf-8")
            elif isinstance(content, bytes):
                encoded = content
            else:
                _fail("producer_bundle_publication_source_invalid")
            if len(encoded) > _MAX_SOURCE_BYTES:
                _fail("producer_bundle_publication_source_too_large")

        # The receipt hashes are canonical JSON identities.  Keep this check here so a caller
        # cannot attach a digest for a different evidence object while staging the same bytes.
        for value, digest, code in ((self.execution_receipt, self.execution_receipt_sha256,
                                     "producer_bundle_publication_execution_receipt_invalid"),
                                    (self.evaluation_receipt, self.evaluation_receipt_sha256,
                                     "producer_bundle_publication_evaluation_receipt_invalid")):
            if value is not None:
                declared = value.get("receipt_sha256")
                expected = declared if isinstance(declared, str) else _sha(_canonical(dict(value)))
                if digest != expected:
                    _fail(code)

    def source_bytes(self) -> dict[str, bytes]:
        return {name: value.encode("utf-8") if isinstance(value, str) else value for name, value in self.source_files.items()}

    def receipt_digest(self) -> str:
        value = self.publication_receipt_sha256 or self.receipt.get("publication_receipt_sha256", self.receipt.get("receipt_sha256"))
        if isinstance(value, str) and len(value) == 64:
            return value
        return _sha(_canonical(dict(self.receipt)))


@dataclass(frozen=True, slots=True)
class ProducerBundlePublicationManifest:
    """Digest manifest for a complete staged publication."""

    journal_id: str
    journal_sha256: str
    preflight_sha256: str
    base_archive_sha256: str
    base_state_sha256: str
    archive_after_sha256: str
    state_after_sha256: str
    candidate_ids: tuple[str, ...]
    files: tuple[dict[str, object], ...]
    status: str = "staged"
    schema_version: str = _SCHEMA_VERSION
    protocol: str = _PROTOCOL
    manifest_sha256: str | None = None

    def _payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "journal_id": self.journal_id,
                "journal_sha256": self.journal_sha256, "preflight_sha256": self.preflight_sha256,
                "base_archive_sha256": self.base_archive_sha256, "base_state_sha256": self.base_state_sha256,
                "archive_after_sha256": self.archive_after_sha256, "state_after_sha256": self.state_after_sha256,
                "candidate_ids": list(self.candidate_ids), "files": list(self.files), "status": self.status}

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION or self.protocol != _PROTOCOL or self.status != "staged":
            _fail("producer_bundle_publication_manifest_invalid")
        if not self.candidate_ids or len(set(self.candidate_ids)) != len(self.candidate_ids):
            _fail("producer_bundle_publication_manifest_invalid")
        for value in (self.journal_sha256, self.preflight_sha256, self.base_archive_sha256, self.base_state_sha256,
                      self.archive_after_sha256, self.state_after_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                _fail("producer_bundle_publication_manifest_invalid")
        expected = _sha(_canonical(self._payload()))
        if self.manifest_sha256 is None:
            object.__setattr__(self, "manifest_sha256", expected)
        elif self.manifest_sha256 != expected:
            _fail("producer_bundle_publication_manifest_digest_mismatch")

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "manifest_sha256": self.manifest_sha256}

    def digest(self) -> str:
        return _sha(_canonical(self._payload()))


# Kept public for recovery's strict parser without importing private helpers.
def marker_payload(*, journal_id: str, journal_sha256: str, manifest_sha256: str, status: str) -> dict[str, object]:
    if status not in {"staged", "unknown"}:
        _fail("producer_bundle_publication_marker_invalid")
    return {"schema_version": _SCHEMA_VERSION, "protocol": _PROTOCOL, "journal_id": journal_id,
            "journal_sha256": journal_sha256, "manifest_sha256": manifest_sha256, "status": status}


def _marker_bytes(payload: dict[str, object]) -> bytes:
    value = {**payload, "marker_sha256": _sha(_canonical(payload))}
    return _pretty(value, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)


def _load_marker(path: Path) -> tuple[dict[str, object], bytes]:
    content = _read(path, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
    try:
        value = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_marker_invalid") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "protocol", "journal_id", "journal_sha256", "manifest_sha256", "status", "marker_sha256"}:
        _fail("producer_bundle_publication_marker_invalid")
    payload = {key: value[key] for key in value if key != "marker_sha256"}
    if value["marker_sha256"] != _sha(_canonical(payload)) or _marker_bytes(payload) != content:
        _fail("producer_bundle_publication_marker_invalid")
    return value, content


def _journal_for_stage(journal: ProducerBundlePublicationJournal, artifacts: Sequence[ProducerBundlePublicationArtifact], rejected_candidate_ids: Sequence[str] = ()) -> ProducerBundlePublicationJournal:
    by_id = {item.candidate_id: item for item in artifacts}
    rejected = tuple(rejected_candidate_ids)
    if len(set(rejected)) != len(rejected) or any(not isinstance(item, str) for item in rejected):
        _fail("producer_bundle_publication_adjudication_invalid")
    candidate_set = {item.candidate_id for item in journal.candidates}
    if not set(rejected) <= candidate_set:
        _fail("producer_bundle_publication_adjudication_invalid")
    if len(by_id) != len(artifacts) or set(by_id) & set(rejected):
        _fail("producer_bundle_publication_candidate_duplicate")
    candidates: list[ProducerBundlePublicationCandidate] = []
    for candidate in journal.candidates:
        artifact = by_id.get(candidate.candidate_id)
        if candidate.status not in {"planned", "rejected", "admitted"}:
            _fail("producer_bundle_publication_state_candidates_invalid")
        if candidate.candidate_id in rejected:
            if candidate.status != "planned" or artifact is not None:
                _fail("producer_bundle_publication_adjudication_invalid")
            candidates.append(replace(candidate, status="rejected"))
            continue
        if candidate.status == "rejected":
            if artifact is not None:
                _fail("producer_bundle_publication_state_candidates_invalid")
            candidates.append(candidate)
            continue
        if artifact is None:
            _fail("producer_bundle_publication_adjudication_missing")
        execution = artifact.execution_receipt_sha256 or candidate.execution_receipt_sha256
        evaluation = artifact.evaluation_receipt_sha256 or candidate.evaluation_receipt_sha256
        publication = artifact.receipt_digest()
        if execution is None or evaluation is None:
            _fail("producer_bundle_publication_receipt_sequence_invalid")
        if candidate.publication_receipt_sha256 is not None and candidate.publication_receipt_sha256 != publication:
            _fail("producer_bundle_publication_receipt_mismatch")
        candidates.append(replace(candidate, status="admitted", execution_receipt_sha256=execution,
                                  evaluation_receipt_sha256=evaluation, publication_receipt_sha256=publication))
    if set(by_id) != {item.candidate_id for item in candidates if item.status == "admitted"}:
        _fail("producer_bundle_publication_adjudication_missing")
    if not any(item.status == "admitted" for item in candidates):
        _fail("producer_bundle_publication_no_admitted_candidates")
    try:
        return replace(journal, state="publishing", publication_phase="staged", candidates=tuple(candidates), journal_sha256=None)
    except TypeError as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_state_invalid") from exc


def _file_descriptor(path: Path, relative: str, content: bytes) -> dict[str, object]:
    info = _regular(path)
    return {"path": relative, "size": len(content), "sha256": _sha(content),
            "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}

def _artifact_entry(batch: Path, artifact: ProducerBundlePublicationArtifact) -> dict[str, object]:
    paths: list[dict[str, object]] = []
    candidate_root = batch / _STAGE_NAME / "candidates" / artifact.candidate_id
    if _present(candidate_root):
        _fail("producer_bundle_publication_staging_conflict")
    candidate_root.mkdir(mode=0o700)
    for relative, content in sorted(artifact.source_bytes().items()):
        parent = Path(relative).parent.as_posix()
        if parent != ".":
            _ensure_directory(candidate_root, parent)
        target = _confined(candidate_root, relative,
                           code="producer_bundle_publication_source_path_invalid")
        _write_new(target, content, maximum=_MAX_SOURCE_BYTES)
        paths.append(_file_descriptor(target, relative, content))
    record_bytes = _pretty(dict(artifact.record), MAX_ARCHIVE_LINE_BYTES)
    receipt_bytes = _pretty(dict(artifact.receipt), MAX_ARCHIVE_LINE_BYTES)
    sidecar_relative = ""
    raw_code_path = artifact.record.get("code_path")
    prefix = f"evolution/candidates/{artifact.candidate_id}/"
    if isinstance(raw_code_path, str) and raw_code_path.startswith(prefix):
        source_relative = raw_code_path.removeprefix(prefix)
        if source_relative in artifact.source_files:
            sidecar_relative = Path(source_relative).parent.as_posix()
            if sidecar_relative == ".":
                sidecar_relative = ""
    sidecar_root = candidate_root if not sidecar_relative else _ensure_directory(candidate_root, sidecar_relative)
    record_path = sidecar_root / "record.json"
    receipt_path = sidecar_root / "receipt.json"
    _write_new(record_path, record_bytes,
               maximum=MAX_ARCHIVE_LINE_BYTES)
    _write_new(receipt_path, receipt_bytes,
               maximum=MAX_ARCHIVE_LINE_BYTES)
    paths.extend((
        _file_descriptor(record_path, str(record_path.relative_to(candidate_root)), record_bytes),
        _file_descriptor(receipt_path, str(receipt_path.relative_to(candidate_root)), receipt_bytes),
    ))
    evidence_root = sidecar_root
    for name, value in (("execution-receipt.json", artifact.execution_receipt),
                        ("evaluation-receipt.json", artifact.evaluation_receipt)):
        if value is None:
            continue
        content = _pretty(dict(value), MAX_ARCHIVE_LINE_BYTES)
        target = evidence_root / name
        _write_new(target, content, maximum=MAX_ARCHIVE_LINE_BYTES)
        paths.append(_file_descriptor(target, str(target.relative_to(candidate_root)), content))
    return {"candidate_id": artifact.candidate_id, "paths": paths,
            "record_sha256": _sha(record_bytes), "receipt_sha256": _sha(receipt_bytes)}


def stage_producer_bundle_publication(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
    preflight: ProducerBundlePreflightReceipt,
    artifacts: Sequence[ProducerBundlePublicationArtifact],
    *,
    state_after: Mapping[str, object],
    rejected_candidate_ids: Sequence[str] = (),
) -> ProducerBundlePublicationManifest:
    """Build and durably retain a complete batch without exposing any candidate."""
    if not isinstance(journal, ProducerBundlePublicationJournal) or not isinstance(preflight, ProducerBundlePreflightReceipt):
        _fail("producer_bundle_publication_input_invalid")
    if journal.state != "prepared":
        _fail("producer_bundle_publication_state_invalid")
    try:
        preflight = parse_producer_bundle_preflight_receipt(preflight.to_dict())
    except Exception as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_preflight_invalid") from exc
    if (
        preflight.journal_id != journal.journal_id
        or preflight.run_id != journal.run_id
        or preflight.task_id != journal.task_id
        or preflight.plan_sha256 != journal.admission_sha256
        or preflight.archive_prefix_sha256 != journal.archive_prefix_sha256
        or preflight.base_archive_sha256 != journal.base_archive_sha256
        or preflight.base_state_sha256 != journal.base_state_sha256
        or preflight.authority_sha256 != _authority_digest(journal)
        or preflight.candidate_ids != tuple(item.candidate_id for item in journal.candidates)
    ):
        _fail("producer_bundle_publication_preflight_mismatch")
    try:
        values = tuple(artifacts)
    except TypeError as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_input_invalid") from exc
    if any(not isinstance(item, ProducerBundlePublicationArtifact) for item in values):
        _fail("producer_bundle_publication_input_invalid")
    if not values and not rejected_candidate_ids:
        _fail("producer_bundle_publication_input_invalid")
    if not isinstance(state_after, Mapping):
        _fail("producer_bundle_publication_state_invalid")
    root = _workspace(workspace)
    batch = _batch(root, journal.journal_id)
    stage = batch / _STAGE_NAME
    if _present(stage):
        _fail("producer_bundle_publication_staging_conflict")
    staged_journal = _journal_for_stage(journal, values, rejected_candidate_ids)
    # The publication order is the immutable plan order, independent of the caller's artifact
    # sequence.  This keeps archive lines, manifest IDs, and candidate moves deterministic.
    by_id = {item.candidate_id: item for item in values}
    values = tuple(
        by_id[item.candidate_id]
        for item in staged_journal.candidates
        if item.status == "admitted"
    )
    evolution = root / "evolution"
    archive_path, state_path = evolution / "archive.jsonl", evolution / "state.json"
    with _locked(root):
        # Reconfirm the base bytes while holding the publication lock; preflight alone is read-only.
        archive = _read(archive_path, MAX_ARCHIVE_BYTES) if _present(archive_path) else b""
        state = _read(state_path, MAX_STATE_BYTES) if _present(state_path) else b""
        if _sha(archive) != journal.base_archive_sha256 or _sha(state) != journal.base_state_sha256:
            _fail("producer_bundle_publication_prefix_drift")
        if archive.count(b"\n") != preflight.record_count:
            _fail("producer_bundle_publication_preflight_mismatch")
        if _present(evolution / _MARKER_NAME):
            _fail("producer_bundle_publication_recovery_required")
        stage.mkdir(mode=0o700)
        (stage / "candidates").mkdir(mode=0o700)
        try:
            entries = tuple(_artifact_entry(batch, item) for item in values)
            lines = []
            for item in values:
                encoded = json.dumps(dict(item.record), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
                if len(encoded) > MAX_ARCHIVE_LINE_BYTES:
                    _fail("producer_bundle_publication_record_too_large")
                lines.append(encoded + b"\n")
            archive_after = archive + b"".join(lines)
            if len(archive_after) > MAX_ARCHIVE_BYTES:
                _fail("producer_bundle_publication_archive_too_large")
            state_after_bytes = _pretty(dict(state_after), MAX_STATE_BYTES)
            _write_new(stage / "archive.jsonl", archive_after, maximum=MAX_ARCHIVE_BYTES)
            _write_new(stage / "state.json", state_after_bytes, maximum=MAX_STATE_BYTES)
            # Persist the exact source journal and preflight evidence alongside the stage.
            staged_journal_bytes = _pretty(staged_journal.to_dict(), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _write_new(batch / "journal.json", staged_journal_bytes, maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _write_new(batch / "journal.staged.json", staged_journal_bytes, maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _write_new(batch / "preflight.json", _pretty(preflight.to_dict(), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            manifest = ProducerBundlePublicationManifest(
                journal_id=journal.journal_id, journal_sha256=staged_journal.digest(),
                preflight_sha256=preflight.digest(), base_archive_sha256=journal.base_archive_sha256,
                base_state_sha256=journal.base_state_sha256, archive_after_sha256=_sha(archive_after),
                state_after_sha256=_sha(state_after_bytes), candidate_ids=tuple(item.candidate_id for item in values),
                files=tuple(entries),
            )
            _write_new(batch / "manifest.json", _pretty(manifest.to_dict(), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            marker = marker_payload(journal_id=journal.journal_id, journal_sha256=staged_journal.digest(), manifest_sha256=manifest.digest(), status="staged")
            _write_new(evolution / _MARKER_NAME, _marker_bytes(marker), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _fsync_dir(stage)
            _fsync_dir(batch)
            return manifest
        except Exception:
            # No marker means no visible publication; leave no ambiguous stage on a known local
            # validation/write failure. A failed marker write is handled as unknown by its caller.
            if not _present(evolution / _MARKER_NAME) and _present(stage):
                import shutil
                shutil.rmtree(stage, ignore_errors=True)
            raise


def _load_manifest(batch: Path) -> ProducerBundlePublicationManifest:
    try:
        value = json.loads(_read(batch / "manifest.json", MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES).decode("utf-8"))
        if not isinstance(value, dict) or value.get("manifest_sha256") is None:
            raise ValueError
        files = value.get("files")
        if not isinstance(files, list):
            raise TypeError("manifest files must be a list")
        return ProducerBundlePublicationManifest(**{**value, "candidate_ids": tuple(value["candidate_ids"]), "files": tuple(files)})
    except ProducerBundlePublicationStagingError:
        raise
    except Exception as exc:
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_manifest_invalid") from exc


def _verify_stage(batch: Path, manifest: ProducerBundlePublicationManifest) -> None:
    stage = batch / _STAGE_NAME
    _directory(stage)
    archive = _read(stage / "archive.jsonl", MAX_ARCHIVE_BYTES)
    state = _read(stage / "state.json", MAX_STATE_BYTES)
    if _sha(archive) != manifest.archive_after_sha256 or _sha(state) != manifest.state_after_sha256:
        _fail("producer_bundle_publication_after_digest_mismatch")
    seen: set[str] = set()
    for entry in manifest.files:
        if not isinstance(entry, dict) or set(entry) != {"candidate_id", "paths", "record_sha256", "receipt_sha256"}:
            _fail("producer_bundle_publication_manifest_invalid")
        candidate_id = entry["candidate_id"]
        if candidate_id not in manifest.candidate_ids or candidate_id in seen or not isinstance(entry["paths"], list):
            _fail("producer_bundle_publication_manifest_invalid")
        seen.add(candidate_id)
        for descriptor in entry["paths"]:
            if not isinstance(descriptor, dict) or set(descriptor) not in ({"path", "size", "sha256"}, {"path", "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns"}):
                _fail("producer_bundle_publication_manifest_invalid")
            raw_path = descriptor["path"]
            if not isinstance(raw_path, str):
                _fail("producer_bundle_publication_manifest_invalid")
            path = (_confined(batch, raw_path) if raw_path.startswith("stage/")
                    else _confined(batch / _STAGE_NAME / "candidates" / candidate_id, raw_path))
            before = _regular(path)
            content = _read(path, _MAX_SOURCE_BYTES)
            after = _regular(path)
            if descriptor["size"] != len(content) or descriptor["sha256"] != _sha(content):
                _fail("producer_bundle_publication_evidence_invalid")
            if set(descriptor) != {"path", "size", "sha256"} and (
                (descriptor["device"], descriptor["inode"], descriptor["mtime_ns"], descriptor["ctime_ns"])
                != (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)
            ):
                _fail("producer_bundle_publication_evidence_changed")
    if seen != set(manifest.candidate_ids):
        _fail("producer_bundle_publication_manifest_invalid")

def commit_producer_bundle_publication(workspace: str | Path, journal: ProducerBundlePublicationJournal) -> ProducerBundlePublicationJournal:
    """Expose one complete staged batch; any uncertain boundary remains terminal."""
    root = _workspace(workspace)
    batch = _batch(root, journal.journal_id)
    evolution = root / "evolution"
    with _locked(root):
        marker, _ = _load_marker(evolution / _MARKER_NAME)
        if marker["journal_id"] != journal.journal_id or marker["status"] != "staged":
            _fail("producer_bundle_publication_recovery_required")
        manifest = _load_manifest(batch)
        try:
            staged_journal = parse_producer_bundle_publication_journal(batch / "journal.json")
        except Exception as exc:
            raise ProducerBundlePublicationStagingError("producer_bundle_publication_journal_invalid") from exc
        if staged_journal.journal_id != journal.journal_id or manifest.journal_sha256 != staged_journal.digest():
            _fail("producer_bundle_publication_manifest_invalid")
        _verify_stage(batch, manifest)
        # Once the first target is moved, all failures are unknown and marker status is durable.
        unknown_marker = marker_payload(journal_id=journal.journal_id, journal_sha256=manifest.journal_sha256,
                                         manifest_sha256=manifest.digest(), status="unknown")
        marker_path = evolution / _MARKER_NAME
        _replace_existing(marker_path, _marker_bytes(unknown_marker), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
        stage = batch / _STAGE_NAME
        try:
            candidates_root = evolution / "candidates"
            if not _present(candidates_root):
                candidates_root.mkdir(mode=0o700)
                _fsync_dir(evolution)
            _directory(candidates_root)
            for candidate_id in manifest.candidate_ids:
                source = stage / "candidates" / candidate_id
                target = candidates_root / candidate_id
                _directory(source)
                if _present(target):
                    _fail("producer_bundle_publication_commit_conflict")
                os.replace(source, target)
                _fsync_dir(candidates_root)
            _replace_file(stage / "archive.jsonl", evolution / "archive.jsonl")
            _replace_file(stage / "state.json", evolution / "state.json")
            after_archive = _read(evolution / "archive.jsonl", MAX_ARCHIVE_BYTES)
            after_state = _read(evolution / "state.json", MAX_STATE_BYTES)
            if _sha(after_archive) != manifest.archive_after_sha256 or _sha(after_state) != manifest.state_after_sha256:
                _fail("producer_bundle_publication_after_digest_mismatch")
            terminal_payload = {"schema_version": _SCHEMA_VERSION, "protocol": _PROTOCOL,
                                "journal_id": journal.journal_id, "journal_sha256": manifest.journal_sha256,
                                "staged_journal_sha256": manifest.journal_sha256,
                                "manifest_sha256": manifest.manifest_sha256,
                                "archive_after_sha256": manifest.archive_after_sha256,
                                "state_after_sha256": manifest.state_after_sha256, "status": "published"}
            terminal = {**terminal_payload, "terminal_marker_sha256": _sha(_canonical(terminal_payload))}
            _write_new(batch / "terminal.json", _pretty(terminal, MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            terminal_digest = terminal["terminal_marker_sha256"]
            final = replace(staged_journal, state="published", publication_phase="committed",
                            terminal_marker_sha256=terminal_digest,
                            archive_after_sha256=manifest.archive_after_sha256,
                            state_after_sha256=manifest.state_after_sha256, journal_sha256=None)
            final_bytes = _pretty(final.to_dict(), MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _write_new(batch / "journal.published.json", final_bytes, maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            _replace_existing(batch / "journal.json", final_bytes, maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
            marker_path.unlink()
            _fsync_dir(evolution)
            return final
        except ProducerBundlePublicationStagingError:
            raise
        except OSError as exc:
            raise ProducerBundlePublicationStagingError("producer_bundle_publication_commit_unknown") from exc


def publish_producer_bundle_publication(*args: Any, **kwargs: Any) -> ProducerBundlePublicationJournal:
    """Convenience API: stage then commit one already-adjudicated batch."""
    stage_producer_bundle_publication(*args, **kwargs)
    workspace, journal = args[0], args[1]
    batch = _batch(_workspace(workspace), journal.journal_id)
    staged = parse_producer_bundle_publication_journal(batch / "journal.json")
    return commit_producer_bundle_publication(workspace, staged)


__all__ = [
    "ProducerBundlePublicationArtifact", "ProducerBundlePublicationManifest",
    "ProducerBundlePublicationStagingError", "commit_producer_bundle_publication",
    "marker_payload", "publish_producer_bundle_publication", "stage_producer_bundle_publication",
]
