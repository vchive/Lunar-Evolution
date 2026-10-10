"""Fail-closed exact-match recovery for staged producer-bundle publication.

Recovery only inspects durable evidence.  It never starts a producer, evaluator, or archive
writer.  A changed byte, path, authority digest, or terminal marker is treated as an
indeterminate publication and cannot be replayed through this API.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_evaluation_spec import strict_json
from .producer_bundle_admission import ProducerBundleAdmissionPlan
from .producer_bundle_preflight import parse_producer_bundle_preflight_receipt
from .producer_bundle_publication import (
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoffError,
    read_python_producer_admission_handoff_pinned,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_JSON_BYTES = 256 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_FILES = 4096
_BATCH_PROTOCOL = "lunar-producer-bundle-publication-v1"
_MANIFEST_PROTOCOL = "lunar-producer-bundle-publication-v1"


class ProducerBundleRecoveryError(ValueError):
    """Fixed-code recovery error; no publication side effect was attempted."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundleRecoveryError(code)


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_json_invalid") from exc
    if len(data) > _MAX_JSON_BYTES:
        _fail("producer_bundle_recovery_too_large")
    return data


def _digest(value: object, code: str = "producer_bundle_recovery_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "producer_bundle_recovery_identifier_invalid") -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _fail(code)
    return value


def _workspace(value: str | Path) -> Path:
    try:
        root = _files.absolute_path(value)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode):
            _fail("producer_bundle_recovery_workspace_invalid")
        return root
    except ProducerBundleRecoveryError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_workspace_invalid") from exc


def _relative(value: object) -> str:
    if (
        not isinstance(value, str) or not value or "\\" in value or "\x00" in value
        or value.startswith("/") or value.endswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or len(value.encode("utf-8")) > 4096
    ):
        _fail("producer_bundle_recovery_path_invalid")
    return value


def _path(root: Path, relative: str, *, directory: Path | None = None) -> Path:
    relative = _relative(relative)
    base = root if directory is None else directory
    result = base.joinpath(*relative.split("/"))
    # lstat every existing component; no caller-controlled symlink can redirect evidence.
    current = base
    for index, part in enumerate(relative.split("/")):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode) or (index < len(relative.split("/")) - 1 and not stat.S_ISDIR(info.st_mode)):
            _fail("producer_bundle_recovery_path_invalid")
    return result


def _read(path: Path, maximum: int = _MAX_JSON_BYTES) -> bytes:
    try:
        return _files.read_regular_file(_files.absolute_path(path), maximum)
    except _files.BenchmarkFileError as exc:
        _fail({
            "missing": "producer_bundle_recovery_missing",
            "too_large": "producer_bundle_recovery_too_large",
            "unsafe": "producer_bundle_recovery_path_invalid",
            "changed": "producer_bundle_recovery_evidence_changed",
        }.get(exc.reason, "producer_bundle_recovery_evidence_invalid"))


def _verify_python_handoff(
    batch: Path, journal: ProducerBundlePublicationJournal,
    plan: ProducerBundleAdmissionPlan,
) -> None:
    """Re-read the immutable Python handoff before resolving any terminal state."""
    try:
        from .producer_bundle_intent import verify_producer_bundle_python_handoff_anchor

        verify_producer_bundle_python_handoff_anchor(batch.parents[2], journal)
        if journal.python_handoff_sha256 is None:
            return
        sidecar = read_python_producer_admission_handoff_pinned(
            batch / "python-producer-admission-handoff.json",
            expected_file_pin=journal.python_handoff_file_pin,
        )
        handoff = sidecar.handoff
        if (sidecar.file_pin != journal.python_handoff_file_pin
                or handoff.handoff_sha256 != journal.python_handoff_sha256):
            raise ValueError("handoff pin mismatch")
        verify_producer_bundle_python_handoff_anchor(batch.parents[2], journal)
    except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_python_handoff_invalid") from exc
    if (
        handoff.run_id != journal.run_id
        or handoff.journal_id != journal.journal_id
        or handoff.parent_task_id != journal.parent_task_id
        or handoff.task_id != journal.task_id
        or handoff.native_execution_receipt_sha256 != journal.native_execution_receipt_sha256
        or handoff.admission_plan_sha256 != plan.digest()
        or handoff.contract_sha256 != journal.contract_sha256
        or handoff.evaluator_sha256 != journal.evaluator_fingerprint
        or handoff.runner_sha256 != journal.runner_fingerprint
        or handoff.dependency_sha256 != journal.dependency_sha256
        or handoff.environment_sha256 != journal.environment_sha256
        or handoff.state != "prepared"
    ):
        _fail("producer_bundle_recovery_python_handoff_mismatch")


def _read_json(path: Path, maximum: int = _MAX_JSON_BYTES) -> dict[str, object]:
    raw = _read(path, maximum)
    try:
        value = strict_json(raw, maximum)
    except Exception as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_json_invalid") from exc
    if not isinstance(value, dict):
        _fail("producer_bundle_recovery_json_invalid")
    return value


def _self_digest(payload: dict[str, object], field: str, code: str) -> str:
    if field not in payload:
        _fail(code)
    given = _digest(payload[field], code)
    body = dict(payload)
    body.pop(field)
    if hashlib.sha256(_canonical(body)).hexdigest() != given:
        _fail(code)
    return given


@dataclass(frozen=True, slots=True)
class ProducerBundleRecoveryResult:
    """A verified read-only decision for one durable publication attempt."""

    status: str  # ``resume``, ``published``, or ``all_rejected``
    journal_sha256: str
    manifest_sha256: str
    preflight_sha256: str
    candidate_ids: tuple[str, ...]
    verified_paths: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"resume", "published", "all_rejected"}:
            _fail("producer_bundle_recovery_status_invalid")
        _digest(self.journal_sha256)
        _digest(self.manifest_sha256)
        _digest(self.preflight_sha256)
        if ((self.status != "all_rejected" and not self.candidate_ids)
                or len(set(self.candidate_ids)) != len(self.candidate_ids)):
            _fail("producer_bundle_recovery_candidates_invalid")
        if any(_IDENTIFIER.fullmatch(value) is None for value in self.candidate_ids):
            _fail("producer_bundle_recovery_candidates_invalid")
        if self.status == "all_rejected":
            if (self.candidate_ids or not self.rejected_candidate_ids
                    or len(set(self.rejected_candidate_ids)) != len(self.rejected_candidate_ids)
                    or any(not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
                           for value in self.rejected_candidate_ids)):
                _fail("producer_bundle_recovery_candidates_invalid")
        elif self.rejected_candidate_ids:
            _fail("producer_bundle_recovery_candidates_invalid")
        if any(not isinstance(value, str) for value in self.verified_paths):
            _fail("producer_bundle_recovery_paths_invalid")


def _batch(root: Path, journal_id: str) -> Path:
    _identifier(journal_id)
    evolution = _path(root, "evolution")
    batches = _path(root, "evolution/producer-batches")
    batch = _path(root, f"evolution/producer-batches/{journal_id}")
    for value in (evolution, batches, batch):
        try:
            info = value.lstat()
            if not stat.S_ISDIR(info.st_mode):
                _fail("producer_bundle_recovery_batch_invalid")
        except FileNotFoundError as exc:
            raise ProducerBundleRecoveryError("producer_bundle_recovery_batch_missing") from exc
    return batch


def _check_preflight(
    value: dict[str, object], journal: ProducerBundlePublicationJournal,
    plan: ProducerBundleAdmissionPlan,
) -> str:
    try:
        receipt = parse_producer_bundle_preflight_receipt(value)
    except Exception as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_preflight_invalid") from exc
    if (
        receipt.journal_id != journal.journal_id or receipt.run_id != journal.run_id
        or receipt.task_id != journal.task_id or receipt.plan_sha256 != plan.digest()
        or receipt.archive_prefix_sha256 != journal.archive_prefix_sha256
        or receipt.base_archive_sha256 != journal.base_archive_sha256
        or receipt.base_state_sha256 != journal.base_state_sha256
        or receipt.candidate_ids != tuple(item.candidate_id for item in journal.candidates)
    ):
        _fail("producer_bundle_recovery_preflight_mismatch")
    return receipt.digest()


def _manifest(
    value: dict[str, object], journal: ProducerBundlePublicationJournal,
    preflight_sha256: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...], dict[str, object]]:
    fields = {
        "schema_version", "protocol", "journal_id", "journal_sha256", "preflight_sha256",
        "base_archive_sha256", "base_state_sha256", "archive_after_sha256", "state_after_sha256",
        "candidate_ids", "files", "status", "manifest_sha256",
    }
    if set(value) != fields or value.get("schema_version") != "1" or value.get("protocol") != _MANIFEST_PROTOCOL:
        _fail("producer_bundle_recovery_manifest_invalid")
    if value["journal_id"] != journal.journal_id or value["journal_sha256"] != journal.journal_sha256:
        _fail("producer_bundle_recovery_manifest_mismatch")
    if value["preflight_sha256"] != preflight_sha256:
        _fail("producer_bundle_recovery_manifest_mismatch")
    for key in ("journal_sha256", "preflight_sha256", "base_archive_sha256", "base_state_sha256", "archive_after_sha256", "state_after_sha256"):
        _digest(value[key], "producer_bundle_recovery_manifest_digest_invalid")
    ids = value["candidate_ids"]
    admitted_ids = tuple(item.candidate_id for item in journal.candidates if item.status == "admitted")
    expected_ids = (
        admitted_ids
        if journal.state in {"publishing", "published"}
        else tuple(item.candidate_id for item in journal.candidates)
    )
    if not isinstance(ids, list) or tuple(ids) != expected_ids:
        _fail("producer_bundle_recovery_manifest_candidates_invalid")
    files = value["files"]
    if not isinstance(files, list) or len(files) != len(ids) or len(files) > _MAX_FILES:
        _fail("producer_bundle_recovery_manifest_files_invalid")
    paths: list[str] = []
    by_id: dict[str, object] = {}
    for item in files:
        if not isinstance(item, dict) or not set(item) <= {
            "candidate_id", "paths", "record_sha256", "receipt_sha256", "retained_evidence",
        } or not {"candidate_id", "paths", "record_sha256", "receipt_sha256"} <= set(item):
            _fail("producer_bundle_recovery_manifest_files_invalid")
        cid = _identifier(item["candidate_id"])
        if cid in by_id or cid not in ids:
            _fail("producer_bundle_recovery_manifest_files_invalid")
        by_id[cid] = item
        _digest(item["record_sha256"], "producer_bundle_recovery_manifest_digest_invalid")
        _digest(item["receipt_sha256"], "producer_bundle_recovery_manifest_digest_invalid")
        declared = item["paths"]
        if not isinstance(declared, list) or not declared or len(declared) > _MAX_FILES:
            _fail("producer_bundle_recovery_manifest_paths_invalid")
        for file in declared:
            if not isinstance(file, dict) or set(file) not in ({"path", "size", "sha256"}, {"path", "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns"}):
                _fail("producer_bundle_recovery_manifest_paths_invalid")
            if set(file) != {"path", "size", "sha256"} and any(
                type(file[name]) is not int or file[name] < 0
                for name in ("device", "inode", "mtime_ns", "ctime_ns")
            ):
                _fail("producer_bundle_recovery_manifest_paths_invalid")
            path = _relative(file["path"])
            if type(file["size"]) is not int or file["size"] < 0 or file["size"] > _MAX_FILE_BYTES:
                _fail("producer_bundle_recovery_manifest_paths_invalid")
            _digest(file["sha256"], "producer_bundle_recovery_manifest_digest_invalid")
            if "device" in file and any(type(file[name]) is not int or file[name] < 0
                                        for name in ("device", "inode", "mtime_ns", "ctime_ns")):
                _fail("producer_bundle_recovery_manifest_paths_invalid")
            paths.append(path)
        retained = item.get("retained_evidence")
        if retained is not None:
            if (
                not isinstance(retained, dict)
                or set(retained) != {"path", "sha256", "evidence_sha256"}
                or not isinstance(retained["path"], str)
            ):
                _fail("producer_bundle_recovery_manifest_files_invalid")
            retained_path = _relative(retained["path"])
            _digest(retained["sha256"], "producer_bundle_recovery_manifest_digest_invalid")
            _digest(retained["evidence_sha256"], "producer_bundle_recovery_manifest_digest_invalid")
            if retained_path not in [
                descriptor.get("path") for descriptor in declared
                if isinstance(descriptor, dict)
            ]:
                _fail("producer_bundle_recovery_manifest_files_invalid")
    if tuple(by_id) != tuple(ids) or len(set(paths)) != len(paths):
        _fail("producer_bundle_recovery_manifest_files_invalid")
    manifest_sha = _self_digest(value, "manifest_sha256", "producer_bundle_recovery_manifest_digest_mismatch")
    return manifest_sha, tuple(ids), tuple(paths), by_id


def _verify_manifest_files(
    root: Path,
    batch: Path,
    manifest_files: dict[str, object],
    journal: ProducerBundlePublicationJournal,
) -> tuple[str, ...]:
    checked: list[str] = []
    for cid, item in manifest_files.items():
        assert isinstance(item, dict)
        staged_root = batch / "stage" / "candidates" / cid
        candidate_root = _path(root, f"stage/candidates/{cid}", directory=batch) if staged_root.exists() else _path(root, f"evolution/candidates/{cid}")
        try:
            info = candidate_root.lstat()
            if not stat.S_ISDIR(info.st_mode):
                _fail("producer_bundle_recovery_manifest_files_invalid")
        except OSError as exc:
            raise ProducerBundleRecoveryError("producer_bundle_recovery_manifest_files_invalid") from exc
        # Native multi-file candidates retain record/receipt beside their entrypoint (for
        # example ``solve/record.json``).  Legacy producer fixtures keep them at the candidate
        # root.  Resolve from the staged manifest paths without guessing outside that tree.
        descriptors = item["paths"]  # type: ignore[index]
        declared_paths = [descriptor["path"] for descriptor in descriptors if isinstance(descriptor, dict)]
        record_relative = "record.json" if "record.json" in declared_paths else next(
            (path for path in declared_paths if isinstance(path, str) and path.endswith("/record.json")), None,
        )
        receipt_relative = "receipt.json" if "receipt.json" in declared_paths else next(
            (path for path in declared_paths if isinstance(path, str) and path.endswith("/receipt.json")), None,
        )
        if not isinstance(record_relative, str) or not isinstance(receipt_relative, str):
            _fail("producer_bundle_recovery_manifest_files_invalid")
        record = _read(candidate_root / record_relative, 64 * 1024)
        receipt = _read(candidate_root / receipt_relative, 64 * 1024)
        if (hashlib.sha256(record).hexdigest() != item["record_sha256"]
                or hashlib.sha256(receipt).hexdigest() != item["receipt_sha256"]):  # type: ignore[index]
            _fail("producer_bundle_recovery_evidence_mismatch")
        candidate = next((entry for entry in journal.candidates if entry.candidate_id == cid), None)
        if candidate is not None and candidate.publication_receipt_sha256 is not None:
            try:
                receipt_value = strict_json(receipt, 64 * 1024)
            except Exception as exc:
                raise ProducerBundleRecoveryError("producer_bundle_recovery_evidence_invalid") from exc
            if not isinstance(receipt_value, dict) or receipt_value.get("publication_receipt_sha256", receipt_value.get("receipt_sha256")) != candidate.publication_receipt_sha256:
                _fail("producer_bundle_recovery_receipt_mismatch")
        for descriptor in item["paths"]:  # type: ignore[index]
            assert isinstance(descriptor, dict)
            raw_path = descriptor["path"]
            raw_path = str(raw_path)
            prefix = f"stage/candidates/{cid}/"
            path = _path(root, raw_path, directory=batch) if raw_path.startswith(prefix) else _path(root, raw_path, directory=candidate_root)
            content = _read(path, int(descriptor["size"]) + 1)
            if len(content) != descriptor["size"] or hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
                _fail("producer_bundle_recovery_evidence_mismatch")
            if "device" in descriptor:
                try:
                    identity = path.lstat()
                    expected_identity = tuple(descriptor[name] for name in ("device", "inode", "size", "mtime_ns", "ctime_ns"))
                    if (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns) != expected_identity:
                        _fail("producer_bundle_recovery_evidence_mismatch")
                except OSError as exc:
                    raise ProducerBundleRecoveryError("producer_bundle_recovery_evidence_invalid") from exc
            checked.append(str(raw_path))
        retained = item.get("retained_evidence")
        evidence = None
        if retained is not None:
            assert isinstance(retained, dict)
            retained_path = retained["path"]
            if not isinstance(retained_path, str):
                _fail("producer_bundle_recovery_manifest_files_invalid")
            evidence_path = _path(root, retained_path, directory=candidate_root)
            evidence_bytes = _read(evidence_path, 64 * 1024)
            if hashlib.sha256(evidence_bytes).hexdigest() != retained["sha256"]:
                _fail("producer_bundle_recovery_evidence_mismatch")
            try:
                evidence = strict_json(evidence_bytes, 64 * 1024)
            except Exception as exc:
                raise ProducerBundleRecoveryError("producer_bundle_recovery_evidence_invalid") from exc
            if not isinstance(evidence, dict) or evidence.get("evidence_sha256") != retained["evidence_sha256"]:
                _fail("producer_bundle_recovery_evidence_mismatch")
        try:
            from .producer_bundle_staging import verify_native_publication_intent

            record_value = strict_json(record, 64 * 1024)
            if not isinstance(record_value, dict):
                _fail("producer_bundle_recovery_evidence_invalid")
            verify_native_publication_intent(
                root, journal, cid, evidence, record=record_value,
            )
        except ProducerBundleRecoveryError:
            raise
        except Exception as exc:
            raise ProducerBundleRecoveryError("producer_bundle_recovery_evidence_changed") from exc
    return tuple(sorted(checked))


def _marker(root: Path, journal: ProducerBundlePublicationJournal) -> None:
    try:
        marker = _read_json(_path(root, "evolution/producer-publication.json"), 8192)
    except ProducerBundleRecoveryError as exc:
        if exc.code == "producer_bundle_recovery_missing":
            return
        raise
    fields = {"schema_version", "protocol", "journal_id", "journal_sha256", "manifest_sha256", "status", "marker_sha256"}
    if set(marker) != fields or marker.get("schema_version") != "1" or marker.get("protocol") != _BATCH_PROTOCOL:
        _fail("producer_bundle_recovery_marker_invalid")
    if marker.get("journal_id") != journal.journal_id or marker.get("journal_sha256") != journal.journal_sha256:
        _fail("producer_bundle_recovery_marker_mismatch")
    _digest(marker["manifest_sha256"], "producer_bundle_recovery_marker_invalid")
    status = marker.get("status")
    if status == "unknown":
        _fail("producer_bundle_recovery_unknown_terminal")
    if status != "staged":
        _fail("producer_bundle_recovery_marker_invalid")
    _self_digest(marker, "marker_sha256", "producer_bundle_recovery_marker_digest_mismatch")


def _terminal(root: Path, batch: Path, journal: ProducerBundlePublicationJournal, manifest_sha: str) -> None:
    value = _read_json(_path(root, "terminal.json", directory=batch), 8192)
    fields = {"schema_version", "protocol", "journal_id", "staged_journal_sha256", "manifest_sha256", "archive_after_sha256", "state_after_sha256", "status", "terminal_marker_sha256"}
    fields_with_alias = fields | {"journal_sha256"}
    if set(value) not in (fields, fields_with_alias) or value.get("schema_version") != "1" or value.get("protocol") != _BATCH_PROTOCOL:
        _fail("producer_bundle_recovery_terminal_invalid")
    staged_path = batch / "journal.staged.json"
    if not staged_path.exists():
        staged_path = batch / "journal.json"
    staged = parse_producer_bundle_publication_journal(staged_path)
    staged_digest = value.get("staged_journal_sha256", value.get("journal_sha256"))
    if value.get("journal_sha256") is not None and value.get("journal_sha256") != staged_digest:
        _fail("producer_bundle_recovery_terminal_mismatch")
    if value.get("journal_id") != journal.journal_id or staged_digest != staged.digest() or value.get("manifest_sha256") != manifest_sha:
        _fail("producer_bundle_recovery_terminal_mismatch")
    if value.get("status") != "published":
        _fail("producer_bundle_recovery_terminal_invalid")
    if value.get("archive_after_sha256") != journal.archive_after_sha256 or value.get("state_after_sha256") != journal.state_after_sha256:
        _fail("producer_bundle_recovery_terminal_mismatch")
    marker_sha = _self_digest(value, "terminal_marker_sha256", "producer_bundle_recovery_terminal_digest_mismatch")
    if journal.terminal_marker_sha256 != marker_sha:
        _fail("producer_bundle_recovery_terminal_mismatch")
    archive = _read(root / "evolution" / "archive.jsonl", _MAX_FILE_BYTES)
    state = _read(root / "evolution" / "state.json", _MAX_FILE_BYTES)
    if hashlib.sha256(archive).hexdigest() != journal.archive_after_sha256 or hashlib.sha256(state).hexdigest() != journal.state_after_sha256:
        _fail("producer_bundle_recovery_after_digest_mismatch")


def resume_producer_bundle_publication(
    workspace: str | Path,
    plan: ProducerBundleAdmissionPlan,
    journal: ProducerBundlePublicationJournal | None = None,
) -> ProducerBundleRecoveryResult:
    """Validate exact durable evidence and return its recovery or terminal decision.

    The supplied plan and journal are compared to their durable canonical files.  Unknown
    publication markers, stale receipts, source changes, and any digest drift fail closed.
    """
    if not isinstance(plan, ProducerBundleAdmissionPlan):
        _fail("producer_bundle_recovery_plan_invalid")
    if journal is None:
        _fail("producer_bundle_recovery_journal_required")
    if not isinstance(journal, ProducerBundlePublicationJournal):
        _fail("producer_bundle_recovery_journal_invalid")
    try:
        from .producer_bundle_intent import validate_producer_bundle_python_handoff_pin

        validate_producer_bundle_python_handoff_pin(journal)
    except (TypeError, ValueError) as exc:
        raise ProducerBundleRecoveryError("producer_bundle_recovery_python_handoff_invalid") from exc
    root = _workspace(workspace)
    batch = _batch(root, journal.journal_id)
    # A successful commit retains the publishing journal as journal.json and writes the
    # terminal, published projection separately.  Never treat the former as success.
    journal_file = "journal.published.json" if journal.state == "published" else "journal.json"
    durable = parse_producer_bundle_publication_journal(_path(root, journal_file, directory=batch))
    if durable != journal:
        # The publication state and per-stage receipts legitimately advance after the
        # caller's prepared journal.  Immutable authority and plan-order mapping must
        # nevertheless be byte-for-byte identical before treating this as the same batch.
        immutable = (
            durable.journal_id == journal.journal_id,
            durable.run_id == journal.run_id,
            durable.parent_task_id == journal.parent_task_id,
            durable.task_id == journal.task_id,
            durable.admission_sha256 == journal.admission_sha256,
            durable.archive_prefix_sha256 == journal.archive_prefix_sha256,
            durable.base_archive_sha256 == journal.base_archive_sha256,
            durable.base_state_sha256 == journal.base_state_sha256,
            durable.contract_sha256 == journal.contract_sha256,
            durable.evaluator_kind == journal.evaluator_kind,
            durable.evaluator_fingerprint == journal.evaluator_fingerprint,
            durable.runner_fingerprint == journal.runner_fingerprint,
            durable.dependency_sha256 == journal.dependency_sha256,
            durable.environment_sha256 == journal.environment_sha256,
            durable.budget_sha256 == journal.budget_sha256,
            durable.native_execution_receipt_sha256 == journal.native_execution_receipt_sha256,
            durable.python_handoff_sha256 == journal.python_handoff_sha256,
            durable.python_handoff_file_pin == journal.python_handoff_file_pin,
            durable.strategy == journal.strategy,
            durable.population_config_sha256 == journal.population_config_sha256,
            durable.num_islands == journal.num_islands,
            tuple((item.candidate_id, item.bundle_id, item.bundle_sha256, item.parent_id,
                   item.generation, item.iteration, item.island_id)
                  for item in durable.candidates)
            == tuple((item.candidate_id, item.bundle_id, item.bundle_sha256, item.parent_id,
                      item.generation, item.iteration, item.island_id)
                     for item in journal.candidates),
        )
        if not all(immutable):
            _fail("producer_bundle_recovery_journal_mismatch")
    if durable.admission_sha256 != plan.digest():
        _fail("producer_bundle_recovery_plan_mismatch")
    _verify_python_handoff(batch, durable, plan)
    if durable.state == "all_rejected":
        try:
            from .producer_bundle_rejection import inspect_producer_bundle_all_rejected

            inspected = inspect_producer_bundle_all_rejected(root, journal)
            if inspected != durable:
                _fail("producer_bundle_recovery_terminal_mismatch")
            manifest = _read_json(_path(root, "rejections.json", directory=batch))
            marker_sha = _self_digest(
                manifest, "terminal_marker_sha256", "producer_bundle_recovery_terminal_digest_mismatch",
            )
            if marker_sha != durable.terminal_marker_sha256:
                _fail("producer_bundle_recovery_terminal_mismatch")
            preflight_sha = _check_preflight(manifest["preflight"], durable, plan)
            checked = tuple(entry["path"] for entry in manifest["entries"])
            _verify_python_handoff(batch, durable, plan)
            return ProducerBundleRecoveryResult(
                "all_rejected", durable.digest(), marker_sha, preflight_sha, (),
                ("journal.prepared.json", "journal.json", "rejections.json", *checked),
                tuple(item.candidate_id for item in durable.candidates),
            )
        except ProducerBundleRecoveryError:
            raise
        except Exception as exc:
            raise ProducerBundleRecoveryError("producer_bundle_recovery_evidence_changed") from exc
    if durable.state == "unknown":
        _fail("producer_bundle_recovery_unknown_terminal")
    # ``prepared`` means preflight has not begun staging.  It is not a recoverable
    # publication attempt; callers must start a fresh staged transaction instead.
    if durable.state == "prepared":
        _fail("producer_bundle_recovery_journal_state_invalid")
    _marker(root, durable)
    preflight_raw = _read_json(_path(root, "preflight.json", directory=batch), 128 * 1024)
    staged_path = batch / "journal.staged.json"
    if not staged_path.exists():
        staged_path = batch / "journal.json"
    staged_journal = parse_producer_bundle_publication_journal(staged_path)
    preflight_sha = _check_preflight(preflight_raw, staged_journal, plan)
    manifest_raw = _read_json(_path(root, "manifest.json", directory=batch), 256 * 1024)
    manifest_sha, ids, _paths, files = _manifest(manifest_raw, staged_journal, preflight_sha)
    checked = _verify_manifest_files(root, batch, files, durable)
    if durable.state == "published":
        _terminal(root, batch, durable, manifest_sha)
        _verify_python_handoff(batch, durable, plan)
        return ProducerBundleRecoveryResult("published", durable.journal_sha256, manifest_sha, preflight_sha, ids, checked)
    if durable.state not in {"executing", "publishing", "failed"}:
        _fail("producer_bundle_recovery_journal_state_invalid")
    stage_archive = _read(_path(root, "stage/archive.jsonl", directory=batch), _MAX_FILE_BYTES)
    stage_state = _read(_path(root, "stage/state.json", directory=batch), _MAX_FILE_BYTES)
    if (hashlib.sha256(stage_archive).hexdigest() != manifest_raw["archive_after_sha256"]
            or hashlib.sha256(stage_state).hexdigest() != manifest_raw["state_after_sha256"]):
        _fail("producer_bundle_recovery_after_digest_mismatch")
    if durable.state == "failed" and any(item.status == "unknown" for item in durable.candidates):
        _fail("producer_bundle_recovery_unknown_terminal")
    _verify_python_handoff(batch, durable, plan)
    return ProducerBundleRecoveryResult("resume", durable.journal_sha256, manifest_sha, preflight_sha, ids, checked)


# Descriptive alias used by callers that only inspect a transaction.
inspect_producer_bundle_publication_resume = resume_producer_bundle_publication


__all__ = [
    "ProducerBundleRecoveryError",
    "ProducerBundleRecoveryResult",
    "inspect_producer_bundle_publication_resume",
    "resume_producer_bundle_publication",
]
