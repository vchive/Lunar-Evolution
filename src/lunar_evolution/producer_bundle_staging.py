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
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as _files
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
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
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoffError,
    read_python_producer_admission_handoff,
)

_PROTOCOL = "lunar-producer-bundle-publication-v1"
_SCHEMA_VERSION = "1"
_MARKER_NAME = "producer-publication.json"
_LOCK_NAME = "producer-publication.lock"
_STAGE_NAME = "stage"
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_HELD_PUBLICATION_LOCKS: ContextVar[tuple[tuple[Path, int, os.stat_result], ...]] = ContextVar(
    "held_producer_publication_locks", default=(),
)


class ProducerBundlePublicationStagingError(ValueError):
    """Fixed-code failure at the staged publication boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundlePublicationStagingError(code)


def _check_held_publication_lock() -> None:
    """Revalidate every active lock in this call context before a filesystem mutation."""
    for lock, descriptor, expected in _HELD_PUBLICATION_LOCKS.get():
        try:
            named = os.lstat(lock)
            held = os.fstat(descriptor)
            if (not stat.S_ISREG(named.st_mode) or held.st_nlink != 1 or named.st_nlink != 1
                    or (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino)
                    or (named.st_dev, named.st_ino) != (expected.st_dev, expected.st_ino)):
                _fail("producer_bundle_publication_lock_changed")
        except OSError as exc:
            raise ProducerBundlePublicationStagingError("producer_bundle_publication_lock_changed") from exc


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
            _check_held_publication_lock()
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


def _verify_python_handoff(batch: Path, journal: ProducerBundlePublicationJournal) -> None:
    """Re-read the durable Python handoff at every direct staging/commit boundary."""
    if journal.python_handoff_sha256 is None:
        return
    try:
        handoff = read_python_producer_admission_handoff(
            batch / "python-producer-admission-handoff.json",
            expected_handoff_sha256=journal.python_handoff_sha256,
        )
    except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
        raise ProducerBundlePublicationStagingError(
            "producer_bundle_publication_python_handoff_invalid"
        ) from exc
    if (
        handoff.run_id != journal.run_id
        or handoff.journal_id != journal.journal_id
        or handoff.parent_task_id != journal.parent_task_id
        or handoff.task_id != journal.task_id
        or handoff.native_execution_receipt_sha256 != journal.native_execution_receipt_sha256
        or handoff.admission_plan_sha256 != journal.admission_sha256
        or handoff.contract_sha256 != journal.contract_sha256
        or handoff.evaluator_sha256 != journal.evaluator_fingerprint
        or handoff.runner_sha256 != journal.runner_fingerprint
        or handoff.dependency_sha256 != journal.dependency_sha256
        or handoff.environment_sha256 != journal.environment_sha256
        or handoff.state != "prepared"
    ):
        _fail("producer_bundle_publication_python_handoff_mismatch")


def _write_new(path: Path, content: bytes, *, maximum: int) -> None:
    _check_held_publication_lock()
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
                _check_held_publication_lock()
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("publication write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _check_held_publication_lock()
        os.link(temporary, path, follow_symlinks=False)
        _check_held_publication_lock()
        os.unlink(temporary)
        _fsync_dir(path.parent)
    except ProducerBundlePublicationStagingError:
        raise
    except OSError as exc:
        try:
            if _present(temporary):
                _check_held_publication_lock()
                temporary.unlink()
        except OSError:
            pass
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_stage_write_failed") from exc


def _replace_existing(path: Path, content: bytes, *, maximum: int) -> None:
    _check_held_publication_lock()
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
                _check_held_publication_lock()
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("publication write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _check_held_publication_lock()
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except ProducerBundlePublicationStagingError:
        raise
    except OSError as exc:
        try:
            if _present(temporary):
                _check_held_publication_lock()
                temporary.unlink()
        except OSError:
            pass
        raise ProducerBundlePublicationStagingError("producer_bundle_publication_commit_unknown") from exc

def _replace_file(source: Path, target: Path) -> None:
    _check_held_publication_lock()
    _regular(source)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        _fail("producer_bundle_publication_commit_conflict")
    try:
        _check_held_publication_lock()
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
def _locked(workspace: Path, *, checkpoint: Callable[[str], object] | None = None):
    _check_held_publication_lock()
    root = workspace / "evolution"
    lock = root / _LOCK_NAME
    if _present(lock):
        _regular(lock)
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("publication lock invalid")
        if checkpoint is None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        else:
            while True:
                checkpoint("producer_publication_lock")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
        current = os.lstat(lock)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise OSError("publication lock replaced")
        token = _HELD_PUBLICATION_LOCKS.set((*_HELD_PUBLICATION_LOCKS.get(), (lock, descriptor, info)))
        try:
            _check_held_publication_lock()
            yield
            _check_held_publication_lock()
        finally:
            _HELD_PUBLICATION_LOCKS.reset(token)
    except (ProducerBundlePublicationStagingError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
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
    # Native bundle publication needs to materialize the exact manifest that was used for the
    # retained attempt.  Generic producer artifacts may omit it and keep the historical shape.
    bundle_manifest: Mapping[str, object] | None = None
    retained_evidence: Mapping[str, object] | None = None

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
        if self.bundle_manifest is not None and not isinstance(self.bundle_manifest, Mapping):
            _fail("producer_bundle_publication_bundle_manifest_invalid")
        if self.retained_evidence is not None and not isinstance(self.retained_evidence, Mapping):
            _fail("producer_bundle_publication_evidence_invalid")
        if self.retained_evidence is not None:
            from .producer_bundle_receipts import _validate_retained_evidence

            try:
                object.__setattr__(self, "retained_evidence", _validate_retained_evidence(self.retained_evidence))
            except Exception as exc:
                if isinstance(exc, ProducerBundlePublicationStagingError):
                    raise
                raise ProducerBundlePublicationStagingError("producer_bundle_publication_evidence_invalid") from exc
        for value, code in ((self.execution_receipt_sha256, "producer_bundle_publication_execution_receipt_invalid"),
                            (self.evaluation_receipt_sha256, "producer_bundle_publication_evaluation_receipt_invalid"),
                            (self.publication_receipt_sha256, "producer_bundle_publication_publication_receipt_invalid")):
            if value is not None and (not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
                _fail(code)
        for name, content in self.source_files.items():
            _safe_relative(name, "producer_bundle_publication_source_path_invalid")
            if name in {"record.json", "receipt.json", "execution-receipt.json", "evaluation-receipt.json", "native-evidence.json"}:
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
                # Known native receipt protocols carry a digest over their payload (excluding
                # the digest field).  Parse them here so a caller cannot self-declare an
                # arbitrary sidecar digest.  Unknown producer protocols remain opaque.
                expected = value.get("receipt_sha256")
                protocol = value.get("protocol")
                if protocol == "lunar-producer-bundle-execution-receipt-v1":
                    from .producer_bundle_receipts import ProducerBundleExecutionReceipt

                    expected = ProducerBundleExecutionReceipt.from_dict(dict(value)).digest()
                elif protocol == "lunar-producer-bundle-evaluation-receipt-v1":
                    from .producer_bundle_receipts import ProducerBundleEvaluationReceipt

                    expected = ProducerBundleEvaluationReceipt.from_dict(dict(value)).digest()
                elif not isinstance(expected, str):
                    expected = _sha(_canonical(dict(value)))
                if digest != expected:
                    _fail(code)
        if self.bundle_manifest is not None:
            try:
                from .candidate_bundle import parse_candidate_source_bundle

                parse_candidate_source_bundle(dict(self.bundle_manifest))
            except Exception as exc:
                raise ProducerBundlePublicationStagingError(
                    "producer_bundle_publication_bundle_manifest_invalid"
                ) from exc

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


def _validate_native_artifact(
    artifact: ProducerBundlePublicationArtifact,
    candidate: ProducerBundlePublicationCandidate,
    journal: ProducerBundlePublicationJournal,
) -> None:
    """Cross-check a native record and its portable evidence before staging bytes.

    The publication layer intentionally accepts opaque producer records for compatibility.  A
    native record advertises ``bundle_evidence`` and therefore has enough structure to validate
    its final source paths, lineage, source manifest, and retained receipt projections here.
    """
    record = artifact.record
    receipt = artifact.receipt
    if record.get("candidate_id") is not None and record.get("candidate_id") != artifact.candidate_id:
        _fail("producer_bundle_publication_candidate_invalid")
    if receipt.get("candidate_id") is not None and receipt.get("candidate_id") != artifact.candidate_id:
        _fail("producer_bundle_publication_candidate_invalid")
    evidence = record.get("bundle_evidence")
    if evidence is None:
        return
    if not isinstance(evidence, Mapping) or artifact.bundle_manifest is None:
        _fail("producer_bundle_publication_evidence_invalid")
    try:
        from .bundle_evolution import validate_bundle_evidence_shape
        from .candidate_bundle import parse_candidate_source_bundle
        from .evolution import Candidate, CandidateReceipt
        from .producer_bundle_receipts import (
            ProducerBundleEvaluationReceipt,
            ProducerBundleExecutionReceipt,
        )

        normalized_evidence = validate_bundle_evidence_shape(dict(evidence))
        if normalized_evidence["bundle_sha256"] != candidate.bundle_sha256:
            _fail("producer_bundle_publication_evidence_invalid")
        bundle = parse_candidate_source_bundle(dict(artifact.bundle_manifest))
        if bundle.digest() != candidate.bundle_sha256:
            _fail("producer_bundle_publication_evidence_invalid")
        if normalized_evidence["bundle_path"] != normalized_evidence["source_root"] + "/bundle-manifest.json":
            _fail("producer_bundle_publication_evidence_invalid")
        expected_root = f"evolution/candidates/{artifact.candidate_id}"
        if normalized_evidence["source_root"] != expected_root:
            _fail("producer_bundle_publication_evidence_invalid")
        code_path = record.get("code_path")
        if code_path != expected_root + "/" + bundle.entrypoint:
            _fail("producer_bundle_publication_evidence_invalid")
        declared = {item.path: item for item in bundle.files}
        if set(artifact.source_files) != set(declared):
            _fail("producer_bundle_publication_source_invalid")
        for path, declaration in declared.items():
            value = artifact.source_files[path]
            content = value.encode("utf-8") if isinstance(value, str) else value
            if not isinstance(content, bytes) or len(content) != declaration.size or _sha(content) != declaration.sha256:
                _fail("producer_bundle_publication_source_invalid")
        entrypoint_bytes = artifact.source_files[bundle.entrypoint]
        entrypoint_bytes = entrypoint_bytes.encode("utf-8") if isinstance(entrypoint_bytes, str) else entrypoint_bytes
        source_sha256 = _sha(entrypoint_bytes)

        # Candidate and ordinary receipt constructors re-check canonical digests, report shape,
        # and the complete evidence projection before the publication transaction can proceed.
        native_candidate = Candidate.from_dict(dict(record))
        native_receipt = CandidateReceipt.from_dict(dict(receipt))
        authority_fields = (
            "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
            "dependency_sha256", "environment_sha256",
        )
        integrity = native_candidate.integrity
        if (
            native_candidate.strategy != journal.strategy
            or native_candidate.candidate_id != artifact.candidate_id
            or native_candidate.bundle_evidence != normalized_evidence
            or native_candidate.source_sha256 != source_sha256
            or native_candidate.receipt_sha256 != native_receipt.receipt_sha256
            or native_receipt.candidate_id != artifact.candidate_id
            or native_receipt.source_sha256 != source_sha256
            or native_receipt.bundle_evidence != normalized_evidence
            or native_candidate.parent_id != candidate.parent_id
            or native_candidate.generation != candidate.generation
            or native_candidate.iteration != candidate.iteration
            or native_candidate.island_id != candidate.island_id
            or any(getattr(native_receipt, field) != getattr(journal, field) for field in authority_fields)
            or not isinstance(integrity, Mapping)
            or any(integrity.get(field) != getattr(journal, field) for field in authority_fields)
            or integrity.get("source_sha256") != source_sha256
            or integrity.get("receipt_sha256") != native_candidate.receipt_sha256
            or integrity.get("bundle_evidence_sha256") != _sha(_canonical(normalized_evidence))
            or native_receipt.evaluation_report().to_dict() != native_candidate.evaluation.to_dict()
        ):
            _fail("producer_bundle_publication_evidence_invalid")

        if artifact.execution_receipt is None or artifact.evaluation_receipt is None:
            _fail("producer_bundle_publication_receipt_sequence_invalid")
        execution = ProducerBundleExecutionReceipt.from_dict(dict(artifact.execution_receipt))
        evaluation = ProducerBundleEvaluationReceipt.from_dict(dict(artifact.evaluation_receipt))
        if (
            execution.candidate_id != artifact.candidate_id
            or execution.bundle_sha256 != normalized_evidence["bundle_sha256"]
            or execution.plan_sha256 != normalized_evidence["plan_sha256"]
            or execution.admission_sha256 != normalized_evidence["admission_sha256"]
            or execution.completion_sha256 != normalized_evidence["completion_sha256"]
            or evaluation.candidate_id != artifact.candidate_id
            or evaluation.bundle_sha256 != normalized_evidence["bundle_sha256"]
            or evaluation.plan_sha256 != normalized_evidence["plan_sha256"]
            or evaluation.admission_sha256 != normalized_evidence["admission_sha256"]
            or evaluation.completion_sha256 != normalized_evidence["completion_sha256"]
            or evaluation.evaluation_sha256 != normalized_evidence["evaluation_sha256"]
            or evaluation.python_handoff_sha256 != journal.python_handoff_sha256
            or evaluation.report != native_candidate.evaluation.to_dict()
            or artifact.execution_receipt_sha256 != execution.digest()
            or artifact.evaluation_receipt_sha256 != evaluation.digest()
        ):
            _fail("producer_bundle_publication_evidence_invalid")
    except ProducerBundlePublicationStagingError:
        raise
    except Exception as exc:
        raise ProducerBundlePublicationStagingError(
            "producer_bundle_publication_evidence_invalid"
        ) from exc


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
        _validate_native_artifact(artifact, candidate, journal)
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

def verify_native_publication_intent(
    workspace: Path,
    journal: ProducerBundlePublicationJournal,
    candidate_id: str,
    retained_evidence: object,
    *,
    record: Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    """Bind retained native drafts to this publication's complete prepared request.

    Generic artifacts and older native artifacts without producer provenance keep their
    historical evidence contract. Native producer records and batches with a prepared intent
    must retain both the fixed draft binding and prepared journal; omitting their descriptor
    cannot downgrade them to that legacy contract. This checks host-retained evidence, not
    signatures against a caller able to rewrite every journal and artifact consistently.
    """
    from .candidate_evaluation_spec import strict_json
    from .producer_bundle_receipts import verify_native_retained_evidence

    code = "producer_bundle_publication_prepared_intent_mismatch"
    prefix = f"evolution/producer-batches/{journal.journal_id}"
    intent_relative = prefix + "/journal.prepared.json"
    binding_relative = prefix + f"/native-drafts/{candidate_id}/draft-binding.json"
    metadata = record.get("metadata") if isinstance(record, Mapping) else None
    required = _present(_confined(workspace, intent_relative)) or (
        isinstance(record, Mapping)
        and record.get("bundle_evidence") is not None
        and isinstance(metadata, Mapping)
        and "producer_bundle" in metadata
    )
    if retained_evidence is None:
        if required:
            _fail(code)
        return None
    evidence = verify_native_retained_evidence(workspace, retained_evidence)
    entries = {item["path"]: item for item in evidence["entries"]}
    bindings: dict[str, dict[str, Any]] = {}
    for relative, entry in entries.items():
        parts = Path(relative).parts
        if (len(parts) != 6 or parts[:2] != ("evolution", "producer-batches")
                or parts[3] != "native-drafts" or parts[5] != "draft-binding.json"):
            continue
        if entry["kind"] != "file":
            _fail(code)
        binding = strict_json(_read(_confined(workspace, relative), 16 * 1024), maximum=16 * 1024)
        if not isinstance(binding, dict):
            _fail(code)
        bindings[relative] = binding
        if "journal_sha256" in binding:
            required = True
    if not required:
        return evidence
    if (set(bindings) != {binding_relative}
            or intent_relative not in entries
            or entries[intent_relative]["kind"] != "file"):
        _fail(code)
    try:
        from .producer_bundle_intent import verify_producer_bundle_prepared_intent

        prepared = replace(
            journal,
            candidates=tuple(replace(
                item, status="planned", execution_receipt_sha256=None,
                evaluation_receipt_sha256=None, publication_receipt_sha256=None,
            ) for item in journal.candidates),
            state="prepared", publication_phase="preflight", terminal_marker_sha256=None,
            archive_after_sha256=None, state_after_sha256=None, journal_sha256=None,
        )
        verify_producer_bundle_prepared_intent(workspace, prepared)
        binding = bindings[binding_relative]
        ordinal = binding.get("ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < len(prepared.candidates):
            _fail(code)
        candidate = prepared.candidates[ordinal]
        if (binding.get("protocol") != "lunar-native-draft-binding-v1"
                or binding.get("journal_sha256") != prepared.digest()
                or binding.get("journal_id") != prepared.journal_id
                or candidate.candidate_id != candidate_id
                or any(binding.get(field) != getattr(candidate, field) for field in (
                    "candidate_id", "bundle_id", "bundle_sha256", "parent_id",
                    "generation", "iteration", "island_id",
                ))):
            _fail(code)
    except ProducerBundlePublicationStagingError:
        raise
    except Exception as exc:
        raise ProducerBundlePublicationStagingError(code) from exc
    return evidence


def _artifact_entry(
    batch: Path,
    artifact: ProducerBundlePublicationArtifact,
    journal: ProducerBundlePublicationJournal,
) -> dict[str, object]:
    evidence = verify_native_publication_intent(
        batch.parents[2], journal, artifact.candidate_id, artifact.retained_evidence,
        record=artifact.record,
    )
    paths: list[dict[str, object]] = []
    candidate_root = batch / _STAGE_NAME / "candidates" / artifact.candidate_id
    if _present(candidate_root):
        _fail("producer_bundle_publication_staging_conflict")
    _check_held_publication_lock()
    candidate_root.mkdir(mode=0o700)
    for relative, content in sorted(artifact.source_bytes().items()):
        parent = Path(relative).parent.as_posix()
        if parent != ".":
            _ensure_directory(candidate_root, parent)
        target = _confined(candidate_root, relative,
                           code="producer_bundle_publication_source_path_invalid")
        _write_new(target, content, maximum=_MAX_SOURCE_BYTES)
        paths.append(_file_descriptor(target, relative, content))
    if artifact.bundle_manifest is not None:
        manifest_bytes = _pretty(dict(artifact.bundle_manifest), MAX_ARCHIVE_LINE_BYTES)
        manifest_path = candidate_root / "bundle-manifest.json"
        _write_new(manifest_path, manifest_bytes, maximum=MAX_ARCHIVE_LINE_BYTES)
        paths.append(_file_descriptor(manifest_path, "bundle-manifest.json", manifest_bytes))
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
    result: dict[str, object] = {"candidate_id": artifact.candidate_id, "paths": paths,
                                 "record_sha256": _sha(record_bytes), "receipt_sha256": _sha(receipt_bytes)}
    if evidence is not None:
        evidence_bytes = _pretty(evidence, MAX_ARCHIVE_LINE_BYTES)
        evidence_target = evidence_root / "native-evidence.json"
        _write_new(evidence_target, evidence_bytes, maximum=MAX_ARCHIVE_LINE_BYTES)
        paths.append(_file_descriptor(evidence_target, str(evidence_target.relative_to(candidate_root)), evidence_bytes))
        result["retained_evidence"] = {
            "path": str(evidence_target.relative_to(candidate_root)),
            "sha256": _sha(evidence_bytes),
            "evidence_sha256": evidence["evidence_sha256"],
        }
    return result


def _validate_native_state_after(
    base_state: bytes,
    state_after: Mapping[str, object],
    journal: ProducerBundlePublicationJournal,
    archive_after: bytes,
) -> None:
    """Validate a native population projection against the staged archive.

    The older producer-only path only changed ``active_ids``.  Native publication also advances
    the population watermark, best candidate, stagnation and integrity digest, so those fields
    are checked against the exact archive bytes assembled in ``stage/archive.jsonl``.
    """
    try:
        before = json.loads(base_state.decode("utf-8"))
        after = json.loads(_canonical(dict(state_after), MAX_STATE_BYTES).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise ProducerBundlePublicationStagingError(
            "producer_bundle_publication_state_invalid"
        ) from exc
    if not isinstance(before, dict) or not isinstance(after, dict):
        _fail("producer_bundle_publication_state_invalid")
    if before.get("strategy") != journal.strategy or after.get("strategy") != journal.strategy:
        _fail("producer_bundle_publication_state_invalid")
    before_config = before.get("config")
    after_config = after.get("config")
    if not isinstance(before_config, dict) or not isinstance(after_config, dict):
        _fail("producer_bundle_publication_state_invalid")
    if before_config != after_config or before_config.get("strategy") != journal.strategy:
        _fail("producer_bundle_publication_state_invalid")
    if before_config.get("num_islands") != journal.num_islands:
        _fail("producer_bundle_publication_state_invalid")
    before_active = before.get("active_ids")
    after_active = after.get("active_ids")
    if not isinstance(before_active, dict) or not isinstance(after_active, dict):
        _fail("producer_bundle_publication_state_invalid")
    admitted = tuple(item for item in journal.candidates if item.status == "admitted")
    if set(after_active) != set(before_active) or any(
        not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        for value in after_active.values()
    ):
        _fail("producer_bundle_publication_state_invalid")
    admitted_ids = {item.candidate_id for item in admitted}
    active_ids = [item for values in after_active.values() for item in values]
    if len(active_ids) != len(set(active_ids)):
        _fail("producer_bundle_publication_state_invalid")
    config_population_size = before_config.get("population_size")
    if (
        isinstance(config_population_size, int)
        and not isinstance(config_population_size, bool)
        and len(active_ids) > config_population_size
    ):
        _fail("producer_bundle_publication_state_invalid")

    # Native state is required to carry the complete marker group.  Recompute its digest from
    # the exact staged archive rather than trusting a caller-provided value.
    marker_fields = {
        "candidate_integrity_schema_version",
        "candidate_integrity_authority",
        "candidate_archive_sha256",
    }
    if marker_fields <= set(after):
        if after.get("candidate_integrity_schema_version") != "1":
            _fail("producer_bundle_publication_state_invalid")
        try:
            from .evolution import Candidate, CandidateIntegrityAuthority
            if len(archive_after) > MAX_ARCHIVE_BYTES:
                _fail("producer_bundle_publication_archive_too_large")
            lines = archive_after.splitlines()
            records = [Candidate.from_dict(json.loads(line.decode("utf-8"))) for line in lines if line]
            ordinary = [item for item in records if "seed_handoff" not in item.metadata]
            archive_digest = _sha(_canonical([item.to_dict() for item in ordinary]))
            authority = CandidateIntegrityAuthority.from_dict(after.get("candidate_integrity_authority"))
        except Exception as exc:
            raise ProducerBundlePublicationStagingError(
                "producer_bundle_publication_state_invalid"
            ) from exc
        if after.get("candidate_archive_sha256") != archive_digest:
            _fail("producer_bundle_publication_state_invalid")
        if any(
            getattr(authority, name) != getattr(journal, name)
            for name in (
                "contract_sha256", "evaluator_kind", "evaluator_fingerprint",
                "runner_fingerprint", "dependency_sha256", "environment_sha256",
            )
        ):
            _fail("producer_bundle_publication_state_invalid")
        known_ids = {item.candidate_id for item in records}
        if not admitted_ids <= known_ids or any(item not in known_ids for item in active_ids):
            _fail("producer_bundle_publication_state_invalid")
    elif marker_fields & set(after):
        _fail("producer_bundle_publication_state_invalid")

    # Immutable authority/config fields cannot drift during publication.  Other state fields are
    # intentionally dynamic and are checked by the transaction's deterministic derivation.
    if after.get("contract_sha256") != before.get("contract_sha256"):
        _fail("producer_bundle_publication_state_invalid")
    if set(before) <= set(after) and any(
        key in {"strategy", "config", "contract_sha256"} and after.get(key) != before.get(key)
        for key in before
    ):
        _fail("producer_bundle_publication_state_invalid")


def stage_producer_bundle_publication(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
    preflight: ProducerBundlePreflightReceipt,
    artifacts: Sequence[ProducerBundlePublicationArtifact],
    *,
    state_after: Mapping[str, object],
    rejected_candidate_ids: Sequence[str] = (),
    checkpoint: Callable[[str], object] | None = None,
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
    _verify_python_handoff(batch, journal)
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
    with _locked(root, checkpoint=checkpoint):
        if checkpoint is not None:
            checkpoint("producer_staging_locked")
        _verify_python_handoff(batch, journal)
        # Reconfirm the base bytes while holding the publication lock; preflight alone is read-only.
        archive = _read(archive_path, MAX_ARCHIVE_BYTES) if _present(archive_path) else b""
        state = _read(state_path, MAX_STATE_BYTES) if _present(state_path) else b""
        if _sha(archive) != journal.base_archive_sha256 or _sha(state) != journal.base_state_sha256:
            _fail("producer_bundle_publication_prefix_drift")
        if archive.count(b"\n") != preflight.record_count:
            _fail("producer_bundle_publication_preflight_mismatch")
        if _present(evolution / _MARKER_NAME):
            _fail("producer_bundle_publication_recovery_required")
        for item in values:
            verify_native_publication_intent(
                root, journal, item.candidate_id, item.retained_evidence, record=item.record,
            )
        _check_held_publication_lock()
        stage.mkdir(mode=0o700)
        _check_held_publication_lock()
        (stage / "candidates").mkdir(mode=0o700)
        try:
            entries = tuple(_artifact_entry(batch, item, journal) for item in values)
            lines = []
            for item in values:
                encoded = json.dumps(dict(item.record), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
                if len(encoded) > MAX_ARCHIVE_LINE_BYTES:
                    _fail("producer_bundle_publication_record_too_large")
                lines.append(encoded + b"\n")
            archive_after = archive + b"".join(lines)
            if len(archive_after) > MAX_ARCHIVE_BYTES:
                _fail("producer_bundle_publication_archive_too_large")
            if any(item.bundle_manifest is not None or item.retained_evidence is not None for item in values):
                _validate_native_state_after(state, state_after, staged_journal, archive_after)
            state_after_bytes = _pretty(dict(state_after), MAX_STATE_BYTES)
            _write_new(stage / "archive.jsonl", archive_after, maximum=MAX_ARCHIVE_BYTES)
            _write_new(stage / "state.json", state_after_bytes, maximum=MAX_STATE_BYTES)
            if checkpoint is not None:
                checkpoint("producer_staging_prepared")
            _verify_python_handoff(batch, staged_journal)
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
                _check_held_publication_lock()
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


def _verify_stage(
    batch: Path, manifest: ProducerBundlePublicationManifest,
    journal: ProducerBundlePublicationJournal,
) -> None:
    stage = batch / _STAGE_NAME
    _directory(stage)
    archive = _read(stage / "archive.jsonl", MAX_ARCHIVE_BYTES)
    state = _read(stage / "state.json", MAX_STATE_BYTES)
    if _sha(archive) != manifest.archive_after_sha256 or _sha(state) != manifest.state_after_sha256:
        _fail("producer_bundle_publication_after_digest_mismatch")
    seen: set[str] = set()
    for entry in manifest.files:
        if not isinstance(entry, dict) or not set(entry) <= {"candidate_id", "paths", "record_sha256", "receipt_sha256", "retained_evidence"} or not {"candidate_id", "paths", "record_sha256", "receipt_sha256"} <= set(entry):
            _fail("producer_bundle_publication_manifest_invalid")
        candidate_id = entry["candidate_id"]
        if candidate_id not in manifest.candidate_ids or candidate_id in seen or not isinstance(entry["paths"], list):
            _fail("producer_bundle_publication_manifest_invalid")
        seen.add(candidate_id)
        record = None
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
            if Path(raw_path).name == "record.json":
                from .candidate_evaluation_spec import strict_json

                record = strict_json(content, maximum=MAX_ARCHIVE_LINE_BYTES)
                if not isinstance(record, dict):
                    _fail("producer_bundle_publication_evidence_invalid")
            after = _regular(path)
            if descriptor["size"] != len(content) or descriptor["sha256"] != _sha(content):
                _fail("producer_bundle_publication_evidence_invalid")
            if set(descriptor) != {"path", "size", "sha256"} and (
                (descriptor["device"], descriptor["inode"], descriptor["mtime_ns"], descriptor["ctime_ns"])
                != (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)
            ):
                _fail("producer_bundle_publication_evidence_changed")
        retained = entry.get("retained_evidence")
        evidence = None
        if retained is not None:
            if (not isinstance(retained, dict)
                    or set(retained) != {"path", "sha256", "evidence_sha256"}
                    or not isinstance(retained["path"], str)
                    or not isinstance(retained["sha256"], str)
                    or not isinstance(retained["evidence_sha256"], str)):
                _fail("producer_bundle_publication_manifest_invalid")
            evidence_path = _confined(batch / _STAGE_NAME / "candidates" / candidate_id, retained["path"])
            evidence_bytes = _read(evidence_path, MAX_ARCHIVE_LINE_BYTES)
            if _sha(evidence_bytes) != retained["sha256"]:
                _fail("producer_bundle_publication_evidence_invalid")
            try:
                evidence = json.loads(evidence_bytes.decode("utf-8"))
            except Exception as exc:
                raise ProducerBundlePublicationStagingError("producer_bundle_publication_evidence_invalid") from exc
            if not isinstance(evidence, dict) or evidence.get("evidence_sha256") != retained["evidence_sha256"]:
                _fail("producer_bundle_publication_evidence_invalid")
        verify_native_publication_intent(
            batch.parents[2], journal, candidate_id, evidence, record=record,
        )
    if seen != set(manifest.candidate_ids):
        _fail("producer_bundle_publication_manifest_invalid")

def commit_producer_bundle_publication(
    workspace: str | Path,
    journal: ProducerBundlePublicationJournal,
    *,
    checkpoint: Callable[[str], object] | None = None,
) -> ProducerBundlePublicationJournal:
    """Expose one complete staged batch; any uncertain boundary remains terminal."""
    root = _workspace(workspace)
    batch = _batch(root, journal.journal_id)
    _verify_python_handoff(batch, journal)
    evolution = root / "evolution"
    with _locked(root, checkpoint=checkpoint):
        if checkpoint is not None:
            checkpoint("producer_commit_locked")
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
        _verify_python_handoff(batch, staged_journal)
        _verify_stage(batch, manifest, staged_journal)
        if checkpoint is not None:
            checkpoint("producer_commit_verified")
        _verify_python_handoff(batch, staged_journal)
        # Once the first target is moved, all failures are unknown and marker status is durable.
        unknown_marker = marker_payload(journal_id=journal.journal_id, journal_sha256=manifest.journal_sha256,
                                         manifest_sha256=manifest.digest(), status="unknown")
        marker_path = evolution / _MARKER_NAME
        _replace_existing(marker_path, _marker_bytes(unknown_marker), maximum=MAX_PRODUCER_BUNDLE_PUBLICATION_BYTES)
        stage = batch / _STAGE_NAME
        try:
            candidates_root = evolution / "candidates"
            if not _present(candidates_root):
                _check_held_publication_lock()
                candidates_root.mkdir(mode=0o700)
                _fsync_dir(evolution)
            _directory(candidates_root)
            for candidate_id in manifest.candidate_ids:
                source = stage / "candidates" / candidate_id
                target = candidates_root / candidate_id
                _directory(source)
                if _present(target):
                    _fail("producer_bundle_publication_commit_conflict")
                _check_held_publication_lock()
                os.replace(source, target)
                _fsync_dir(candidates_root)
            _replace_file(stage / "archive.jsonl", evolution / "archive.jsonl")
            _replace_file(stage / "state.json", evolution / "state.json")
            after_archive = _read(evolution / "archive.jsonl", MAX_ARCHIVE_BYTES)
            after_state = _read(evolution / "state.json", MAX_STATE_BYTES)
            if _sha(after_archive) != manifest.archive_after_sha256 or _sha(after_state) != manifest.state_after_sha256:
                _fail("producer_bundle_publication_after_digest_mismatch")
            _verify_python_handoff(batch, staged_journal)
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
            _verify_python_handoff(batch, final)
            _check_held_publication_lock()
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
