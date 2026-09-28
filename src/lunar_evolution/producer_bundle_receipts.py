"""Canonical execution and evaluation receipts for producer bundle publication.

The native multi-file pipeline already retains the authoritative plan, admission, execution
attempt, and independent evaluation trees.  This module projects those records into small,
portable receipts consumed by :mod:`producer_bundle_staging`.  The projection is deliberately
hash-oriented: it carries no process IDs, paths outside the journal, evaluator stdout, or
producer claims.  Receipt construction only inspects retained evidence and never executes or
retries a candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files
from .candidate_bundle import MAX_CANDIDATE_BUNDLE_BYTES, parse_candidate_source_bundle
from .candidate_evaluation import CandidateEvaluationResult, inspect_candidate_evaluation
from .candidate_evaluation_spec import canonical_json, strict_json
from .candidate_execution import admit_candidate_execution
from .candidate_execution_evidence import (
    CandidateExecutionRecord,
    inspect_candidate_execution_record,
)
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .evolution import Candidate, CandidateIntegrityAuthority, CandidateReceipt

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_RECEIPT_BYTES = 64 * 1024
_EXECUTION_FIELDS = {
    "schema_version", "protocol", "candidate_id", "bundle_sha256", "plan_sha256",
    "admission_sha256", "completion_sha256", "launch_intent_sha256", "result_sha256",
    "runner_result_sha256", "cleanup_sha256", "status", "runner_status", "cleanup_status",
    "receipt_sha256",
}
_EVALUATION_FIELDS = {
    "schema_version", "protocol", "candidate_id", "bundle_sha256", "plan_sha256",
    "admission_sha256", "completion_sha256", "evaluation_sha256", "binding", "report",
    "output_contract_valid", "harness_invoked", "status", "receipt_sha256",
}
_EXECUTION_PROTOCOL = "lunar-producer-bundle-execution-receipt-v1"
_EVALUATION_PROTOCOL = "lunar-producer-bundle-evaluation-receipt-v1"
_RETAINED_EVIDENCE_PROTOCOL = "lunar-native-retained-evidence-v1"
_RETAINED_EVIDENCE_FIELDS = {
    "schema_version", "protocol", "entries", "evidence_sha256",
}
_RETAINED_ENTRY_FIELDS = {
    "path", "kind", "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns",
}
_MAX_RETAINED_EVIDENCE_ENTRIES = 4096


class ProducerBundleReceiptError(ValueError):
    """Fixed-code failure while projecting retained native candidate evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundleReceiptError(code)


def _digest(value: object, code: str = "producer_bundle_receipt_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "producer_bundle_receipt_identifier_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_canonical_invalid") from exc
    if len(data) > _MAX_RECEIPT_BYTES:
        _fail("producer_bundle_receipt_too_large")
    return data


def _object(value: object, fields: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest_payload(value: Mapping[str, Any], digest_name: str) -> str:
    payload = {key: value[key] for key in value if key != digest_name}
    return _sha(payload)


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code)
    try:
        # Round-trip through canonical JSON to detach nested caller-owned containers as well as
        # the top-level mapping.  A shallow copy would let a later nested mutation invalidate the
        # receipt identity after construction.
        encoded = _canonical(dict(value))
        result = json.loads(encoded)
        if not isinstance(result, dict):
            _fail(code)
        return result
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError(code) from exc


def _retained_evidence_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1", "protocol": _RETAINED_EVIDENCE_PROTOCOL,
        "entries": entries,
    }


def _retained_evidence_digest(value: Mapping[str, Any]) -> str:
    return _sha(_retained_evidence_payload(list(value["entries"])))


def _validate_retained_evidence(value: object) -> dict[str, Any]:
    raw = _mapping(value, "producer_bundle_retained_evidence_invalid")
    if set(raw) != _RETAINED_EVIDENCE_FIELDS or raw.get("schema_version") != "1" or raw.get("protocol") != _RETAINED_EVIDENCE_PROTOCOL:
        _fail("producer_bundle_retained_evidence_invalid")
    entries = raw.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_RETAINED_EVIDENCE_ENTRIES:
        _fail("producer_bundle_retained_evidence_invalid")
    previous = None
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _RETAINED_ENTRY_FIELDS:
            _fail("producer_bundle_retained_evidence_invalid")
        path = entry.get("path")
        if (not isinstance(path, str) or not path.startswith("evolution/") or "\x00" in path
                or Path(path).is_absolute() or any(part in {"", ".", ".."} for part in Path(path).parts)):
            _fail("producer_bundle_retained_evidence_path_invalid")
        if previous is not None and path <= previous:
            _fail("producer_bundle_retained_evidence_order_invalid")
        previous = path
        kind = entry.get("kind")
        if kind not in {"file", "directory"}:
            _fail("producer_bundle_retained_evidence_invalid")
        size = entry.get("size")
        if kind == "file":
            if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > 16 * 1024 * 1024:
                _fail("producer_bundle_retained_evidence_invalid")
            if not isinstance(entry.get("sha256"), str) or _SHA256.fullmatch(entry["sha256"]) is None:
                _fail("producer_bundle_retained_evidence_invalid")
        elif size is not None or entry.get("sha256") is not None:
            _fail("producer_bundle_retained_evidence_invalid")
        for name in ("device", "inode", "mtime_ns", "ctime_ns"):
            number = entry.get(name)
            if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                _fail("producer_bundle_retained_evidence_invalid")
        normalized.append(dict(entry))
    if raw.get("evidence_sha256") != _retained_evidence_digest({"entries": normalized}):
        _fail("producer_bundle_retained_evidence_digest_mismatch")
    return {"schema_version": "1", "protocol": _RETAINED_EVIDENCE_PROTOCOL,
            "entries": normalized, "evidence_sha256": raw["evidence_sha256"]}


def _retained_entry(path: Path, workspace: Path) -> dict[str, Any]:
    try:
        relative = path.relative_to(workspace).as_posix()
        info = os.lstat(path)
    except (OSError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_retained_evidence_invalid") from exc
    if stat.S_ISLNK(info.st_mode):
        _fail("producer_bundle_retained_evidence_path_invalid")
    if stat.S_ISDIR(info.st_mode):
        kind, size, digest = "directory", None, None
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        try:
            content = _files.read_regular_file(path, 16 * 1024 * 1024, exact_size=False)
        except Exception as exc:
            raise ProducerBundleReceiptError("producer_bundle_retained_evidence_invalid") from exc
        kind, size, digest = "file", len(content), hashlib.sha256(content).hexdigest()
    else:
        _fail("producer_bundle_retained_evidence_path_invalid")
    return {"path": relative, "kind": kind, "size": size, "sha256": digest,
            "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _collect_retained_evidence(workspace: Path, roots: tuple[Path, ...]) -> dict[str, Any]:
    paths: set[Path] = set()
    for root in roots:
        if root.is_symlink() or not root.exists():
            _fail("producer_bundle_retained_evidence_path_invalid")
        paths.add(root)
        if root.is_dir():
            for current, directories, files in os.walk(root, topdown=True, followlinks=False):
                current_path = Path(current)
                for name in sorted(directories + files):
                    candidate = current_path / name
                    if candidate.is_symlink():
                        _fail("producer_bundle_retained_evidence_path_invalid")
                    paths.add(candidate)
                directories[:] = sorted(directories)
                files[:] = sorted(files)
    entries = sorted((_retained_entry(path, workspace) for path in paths), key=lambda item: item["path"])
    if not entries or len(entries) > _MAX_RETAINED_EVIDENCE_ENTRIES:
        _fail("producer_bundle_retained_evidence_invalid")
    payload = _retained_evidence_payload(entries)
    return {**payload, "evidence_sha256": _sha(payload)}


def verify_native_retained_evidence(workspace: str | Path, value: object) -> dict[str, Any]:
    """Revalidate native retained paths and their original bytes/inodes."""
    evidence = _validate_retained_evidence(value)
    root = _files.absolute_path(workspace)
    for entry in evidence["entries"]:
        path = root / entry["path"]
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ProducerBundleReceiptError("producer_bundle_retained_evidence_missing") from exc
        if stat.S_ISLNK(info.st_mode) or (entry["kind"] == "directory" and not stat.S_ISDIR(info.st_mode)):
            _fail("producer_bundle_retained_evidence_path_invalid")
        if entry["kind"] == "file":
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                _fail("producer_bundle_retained_evidence_path_invalid")
            try:
                content = _files.read_regular_file(path, 16 * 1024 * 1024)
            except Exception as exc:
                raise ProducerBundleReceiptError("producer_bundle_retained_evidence_changed") from exc
            if hashlib.sha256(content).hexdigest() != entry["sha256"] or len(content) != entry["size"]:
                _fail("producer_bundle_retained_evidence_changed")
        elif not stat.S_ISDIR(info.st_mode):
            _fail("producer_bundle_retained_evidence_path_invalid")
        if (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns) != (
            entry["device"], entry["inode"], entry["mtime_ns"], entry["ctime_ns"]
        ):
            _fail("producer_bundle_retained_evidence_changed")
    return evidence


def _receipt_value(value: object, *, fields: set[str], protocol: str, code: str) -> dict[str, Any]:
    raw = _object(value, fields, code)
    if raw.get("schema_version") != "1" or raw.get("protocol") != protocol:
        _fail(code)
    _digest(raw.get("receipt_sha256"), code)
    if _digest_payload(raw, "receipt_sha256") != raw["receipt_sha256"]:
        _fail("producer_bundle_receipt_digest_mismatch")
    _canonical(raw)
    return raw


def _normal_report(value: object) -> dict[str, Any]:
    report = _mapping(value, "producer_bundle_evaluation_report_invalid")
    # The native report parser already normalizes evaluator error prose.  Keep only the bounded
    # public report shape; receipt parsing re-checks canonical JSON at every boundary.
    required = {"schema_version", "evaluator_id", "validity", "quality", "combined_score", "detailed_scores", "error_info"}
    if set(report) != required or report.get("schema_version") != "1":
        _fail("producer_bundle_evaluation_report_invalid")
    if type(report["validity"]) is not int or report["validity"] not in (0, 1):
        _fail("producer_bundle_evaluation_report_invalid")
    if not isinstance(report["evaluator_id"], str) or not _ID.fullmatch(report["evaluator_id"]):
        _fail("producer_bundle_evaluation_report_invalid")
    if not isinstance(report["detailed_scores"], dict) or not isinstance(report["error_info"], list):
        _fail("producer_bundle_evaluation_report_invalid")
    _canonical(report)
    return report


@dataclass(frozen=True, slots=True)
class ProducerBundleExecutionReceipt:
    """Portable projection of one verified native execution attempt."""

    candidate_id: str
    bundle_sha256: str
    plan_sha256: str
    admission_sha256: str
    completion_sha256: str
    launch_intent_sha256: str
    result_sha256: str
    runner_result_sha256: str
    cleanup_sha256: str
    status: str = "recorded"
    runner_status: str = "succeeded"
    cleanup_status: str = "verified"
    schema_version: str = "1"
    protocol: str = _EXECUTION_PROTOCOL
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.candidate_id)
        for field in (
            "bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256",
            "launch_intent_sha256", "result_sha256", "runner_result_sha256", "cleanup_sha256",
        ):
            _digest(getattr(self, field), "producer_bundle_execution_receipt_digest_invalid")
        if self.schema_version != "1" or self.protocol != _EXECUTION_PROTOCOL:
            _fail("producer_bundle_execution_receipt_schema_invalid")
        if self.status != "recorded" or self.runner_status != "succeeded":
            _fail("producer_bundle_execution_receipt_status_invalid")
        if self.cleanup_status != "verified":
            _fail("producer_bundle_execution_receipt_cleanup_invalid")
        expected = _digest_payload(self.to_dict(include_receipt_sha256=False), "receipt_sha256")
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_bundle_receipt_digest_mismatch")
        _canonical(self.to_dict())

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "candidate_id": self.candidate_id, "bundle_sha256": self.bundle_sha256,
            "plan_sha256": self.plan_sha256, "admission_sha256": self.admission_sha256,
            "completion_sha256": self.completion_sha256,
            "launch_intent_sha256": self.launch_intent_sha256,
            "result_sha256": self.result_sha256, "runner_result_sha256": self.runner_result_sha256,
            "cleanup_sha256": self.cleanup_sha256, "status": self.status,
            "runner_status": self.runner_status, "cleanup_status": self.cleanup_status,
        }
        if include_receipt_sha256:
            value["receipt_sha256"] = self.receipt_sha256
        return value

    def digest(self) -> str:
        return str(self.receipt_sha256)

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleExecutionReceipt:
        raw = _receipt_value(value, fields=_EXECUTION_FIELDS, protocol=_EXECUTION_PROTOCOL,
                             code="producer_bundle_execution_receipt_schema_invalid")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ProducerBundleEvaluationReceipt:
    """Portable projection of one independent native evaluation snapshot."""

    candidate_id: str
    bundle_sha256: str
    plan_sha256: str
    admission_sha256: str
    completion_sha256: str
    evaluation_sha256: str
    binding: dict[str, Any]
    report: dict[str, Any]
    output_contract_valid: bool
    harness_invoked: bool
    status: str = "evaluated"
    schema_version: str = "1"
    protocol: str = _EVALUATION_PROTOCOL
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.candidate_id)
        for field in (
            "bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256", "evaluation_sha256",
        ):
            _digest(getattr(self, field), "producer_bundle_evaluation_receipt_digest_invalid")
        if self.schema_version != "1" or self.protocol != _EVALUATION_PROTOCOL:
            _fail("producer_bundle_evaluation_receipt_schema_invalid")
        if self.status != "evaluated" or type(self.output_contract_valid) is not bool or type(self.harness_invoked) is not bool:
            _fail("producer_bundle_evaluation_receipt_status_invalid")
        binding = _mapping(self.binding, "producer_bundle_evaluation_binding_invalid")
        report = _normal_report(self.report)
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "report", report)
        expected = _digest_payload(self.to_dict(include_receipt_sha256=False), "receipt_sha256")
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_bundle_receipt_digest_mismatch")
        _canonical(self.to_dict())

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "candidate_id": self.candidate_id, "bundle_sha256": self.bundle_sha256,
            "plan_sha256": self.plan_sha256, "admission_sha256": self.admission_sha256,
            "completion_sha256": self.completion_sha256,
            "evaluation_sha256": self.evaluation_sha256, "binding": self.binding,
            "report": self.report, "output_contract_valid": self.output_contract_valid,
            "harness_invoked": self.harness_invoked, "status": self.status,
        }
        if include_receipt_sha256:
            value["receipt_sha256"] = self.receipt_sha256
        return value

    def digest(self) -> str:
        return str(self.receipt_sha256)

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleEvaluationReceipt:
        raw = _receipt_value(value, fields=_EVALUATION_FIELDS, protocol=_EVALUATION_PROTOCOL,
                             code="producer_bundle_evaluation_receipt_schema_invalid")
        return cls(**raw)


def _verified_candidate_evidence(workspace: str | Path, candidate: Candidate) -> tuple[dict[str, Any], Any, Any, CandidateExecutionRecord, CandidateEvaluationResult]:
    """Return the exact retained plan/admission/attempt/evaluation evidence for a candidate."""
    if not isinstance(candidate, Candidate) or candidate.bundle_evidence is None or not isinstance(candidate.integrity, dict):
        _fail("producer_bundle_receipt_candidate_invalid")
    from .bundle_evolution import validate_bundle_evidence_shape, validate_candidate_bundle_evidence

    try:
        value = validate_bundle_evidence_shape(candidate.bundle_evidence)
        authority_fields = set(CandidateIntegrityAuthority.__dataclass_fields__)
        authority = CandidateIntegrityAuthority.from_dict({name: candidate.integrity[name] for name in authority_fields})
        root = _files.absolute_path(workspace)
        # This verifies source bytes, archive receipt, execution and evaluation binding before
        # constructing either portable receipt.
        result = validate_candidate_bundle_evidence(
            root, value, code_path=candidate.code_path, evaluation=candidate.evaluation, authority=authority,
        )
        run = root / value["run_root"]
        plan = parse_candidate_workspace_plan(run / "plan.json")
        admission = admit_candidate_execution(
            _files.read_regular_file(run / "admission.json", 256 * 1024), plan=plan,
            expected_admission_sha256=value["admission_sha256"], expected_plan_sha256=value["plan_sha256"],
            expected_bundle_sha256=value["bundle_sha256"], expected_contract_sha256=authority.contract_sha256,
        ).admission
        record = inspect_candidate_execution_record(
            run / "attempt", plan=plan, admission=admission,
            expected_completion_sha256=value["completion_sha256"],
        )
        return value, plan, admission, record, result
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_evidence_invalid") from exc


def build_producer_bundle_execution_receipt(
    workspace: str | Path, candidate: Candidate,
) -> ProducerBundleExecutionReceipt:
    """Project a successful, independently cleaned native attempt into a receipt."""
    value, _plan, _admission, record, _result = _verified_candidate_evidence(workspace, candidate)
    projection = record.to_dict()
    runner = projection.get("runner_result")
    if not isinstance(runner, dict):
        _fail("producer_bundle_execution_receipt_evidence_invalid")
    try:
        return ProducerBundleExecutionReceipt(
            candidate_id=candidate.candidate_id, bundle_sha256=value["bundle_sha256"],
            plan_sha256=value["plan_sha256"], admission_sha256=value["admission_sha256"],
            completion_sha256=value["completion_sha256"],
            launch_intent_sha256=record.launch_intent_sha256,  # type: ignore[arg-type]
            result_sha256=record.result_sha256,  # type: ignore[arg-type]
            runner_result_sha256=record.runner_result_sha256,  # type: ignore[arg-type]
            cleanup_sha256=record.cleanup_sha256,  # type: ignore[arg-type]
            status=projection.get("status", "unknown"), runner_status=runner.get("status", "unknown"),
            cleanup_status=projection.get("cleanup", record.cleanup_status),
        )
    except ProducerBundleReceiptError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_execution_receipt_evidence_invalid") from exc


def build_producer_bundle_evaluation_receipt(
    workspace: str | Path, candidate: Candidate,
) -> ProducerBundleEvaluationReceipt:
    """Project one retained independent evaluation snapshot into a portable receipt."""
    value, _plan, _admission, _record, result = _verified_candidate_evidence(workspace, candidate)
    projection = result.to_dict()
    try:
        return ProducerBundleEvaluationReceipt(
            candidate_id=candidate.candidate_id, bundle_sha256=value["bundle_sha256"],
            plan_sha256=value["plan_sha256"], admission_sha256=value["admission_sha256"],
            completion_sha256=value["completion_sha256"], evaluation_sha256=result.digest(),
            binding=dict(projection["binding"]), report=dict(projection["report"]),
            output_contract_valid=projection["output_contract_valid"],
            harness_invoked=projection["harness_invoked"], status=projection["status"],
        )
    except ProducerBundleReceiptError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_evaluation_receipt_evidence_invalid") from exc


def build_native_producer_bundle_execution_receipt(
    result: Any, *, candidate_id: str | None = None,
) -> ProducerBundleExecutionReceipt:
    """Project a retained, non-publishing native draft execution into a portable receipt."""
    try:
        resolved_id = candidate_id or result.candidate_id
        record = result.execution
        projection = record.to_dict()
        runner = projection.get("runner_result")
        if not isinstance(runner, dict):
            _fail("producer_bundle_execution_receipt_evidence_invalid")
        return ProducerBundleExecutionReceipt(
            candidate_id=resolved_id, bundle_sha256=result.bundle.digest(),
            plan_sha256=result.plan.digest(), admission_sha256=result.admission.digest(),
            completion_sha256=record.completion_sha256,
            launch_intent_sha256=record.launch_intent_sha256,
            result_sha256=record.result_sha256,
            runner_result_sha256=record.runner_result_sha256,
            cleanup_sha256=record.cleanup_sha256,
            status=projection.get("status", "unknown"),
            runner_status=runner.get("status", "unknown"),
            cleanup_status=projection.get("cleanup", record.cleanup_status),
        )
    except ProducerBundleReceiptError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_execution_receipt_evidence_invalid") from exc


def build_native_producer_bundle_evaluation_receipt(
    result: Any, *, candidate_id: str | None = None,
) -> ProducerBundleEvaluationReceipt:
    """Project a retained, non-publishing independent evaluation into a portable receipt."""
    try:
        resolved_id = candidate_id or result.candidate_id
        evaluation = result.evaluation
        projection = evaluation.to_dict()
        return ProducerBundleEvaluationReceipt(
            candidate_id=resolved_id, bundle_sha256=result.bundle.digest(),
            plan_sha256=result.plan.digest(), admission_sha256=result.admission.digest(),
            completion_sha256=result.execution.completion_sha256,
            evaluation_sha256=evaluation.digest(), binding=dict(projection["binding"]),
            report=dict(projection["report"]), output_contract_valid=projection["output_contract_valid"],
            harness_invoked=projection["harness_invoked"], status=projection["status"],
        )
    except ProducerBundleReceiptError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_evaluation_receipt_evidence_invalid") from exc


def build_native_producer_bundle_publication_artifact(
    workspace: str | Path, result: Any, *, authority: CandidateIntegrityAuthority,
) -> Any:
    """Build a planned publication artifact from a non-publishing native result.

    The source bytes remain in the private batch tree and the retained run/evaluation paths are
    referenced in the evidence binding.  The returned artifact is portable staging input; this
    function does not write the live candidate tree or archive.
    """
    from .bundle_evolution import (
        _DRAFT_BINDING_NAME,
        _draft_binding,
        _runner_digest,
        validate_bundle_evidence_shape,
    )
    from .producer_bundle_staging import ProducerBundlePublicationArtifact

    try:
        root = _files.absolute_path(workspace)
        if not isinstance(authority, CandidateIntegrityAuthority):
            authority = CandidateIntegrityAuthority.from_dict(dict(authority))
        candidate_id = result.candidate_id
        entrypoint = result.bundle.entrypoint
        source_root = _files.absolute_path(result.source_root)
        run_root = _files.absolute_path(result.run_root)
        source_relative = source_root.relative_to(root).as_posix()
        run_relative = run_root.relative_to(root).as_posix()
        expected_source = f"evolution/producer-batches/{result.journal_id}/native-drafts/{candidate_id}/source"
        expected_run = f"evolution/bundle-attempts/.bundle-run-{result.run_id}"
        if source_relative != expected_source or run_relative != expected_run:
            _fail("producer_bundle_receipt_evidence_invalid")

        # Reopen every retained native record before projecting it.  The in-memory result is
        # useful for the caller, but it is not evidence of what remains on disk after the run.
        try:
            bundle_manifest_bytes = _files.read_regular_file(
                source_root / "bundle-manifest.json", MAX_CANDIDATE_BUNDLE_BYTES,
            )
            bundle = parse_candidate_source_bundle(strict_json(bundle_manifest_bytes))
        except Exception as exc:
            raise ProducerBundleReceiptError("producer_bundle_receipt_source_invalid") from exc
        if bundle.digest() != result.bundle.digest():
            _fail("producer_bundle_receipt_source_invalid")
        try:
            from .candidate_bundle import verify_candidate_source_bundle

            verify_candidate_source_bundle(
                bundle, source_root=source_root, contract_sha256=authority.contract_sha256,
                expected_bundle_sha256=bundle.digest(),
            )
        except Exception as exc:
            raise ProducerBundleReceiptError("producer_bundle_receipt_source_invalid") from exc

        binding_path = source_root.parent / _DRAFT_BINDING_NAME
        binding_bytes = _files.read_regular_file(binding_path, 16 * 1024)
        binding = strict_json(binding_bytes, maximum=16 * 1024)
        source_identity = os.stat(source_root, follow_symlinks=False)
        run_identity = os.stat(run_root, follow_symlinks=False)
        expected_binding = _draft_binding(
            journal_id=result.journal_id, candidate_id=candidate_id, run_id=result.run_id,
            bundle_id=result.bundle_id, bundle_sha256=bundle.digest(), ordinal=result.ordinal,
            parent_id=result.parent_id, generation=result.generation, iteration=result.iteration,
            island_id=result.island_id, source_root=source_relative,
            source_identity=(source_identity.st_dev, source_identity.st_ino), run_root=run_relative,
            run_identity=(run_identity.st_dev, run_identity.st_ino),
            plan_sha256=result.plan.digest(), admission_sha256=result.admission.digest(),
            journal_sha256=result.journal_sha256,
        )
        if canonical_json(binding) != binding_bytes or binding != expected_binding:
            _fail("producer_bundle_receipt_evidence_invalid")

        plan = parse_candidate_workspace_plan(run_root / "plan.json")
        if plan.digest() != result.plan.digest() or plan.to_dict() != result.plan.to_dict():
            _fail("producer_bundle_receipt_evidence_invalid")
        admission_bytes = _files.read_regular_file(run_root / "admission.json", 256 * 1024)
        admission = admit_candidate_execution(
        admission_bytes, plan=plan, expected_admission_sha256=result.admission.digest(),
            expected_plan_sha256=plan.digest(), expected_bundle_sha256=bundle.digest(),
            expected_contract_sha256=authority.contract_sha256,
        ).admission
        if admission.to_dict() != result.admission.to_dict():
            _fail("producer_bundle_receipt_evidence_invalid")
        if (
            admission.evaluator.kind != authority.evaluator_kind
            or admission.evaluator.fingerprint != authority.evaluator_fingerprint
            or admission.dependency_sha256 != authority.dependency_sha256
            or admission.environment_sha256 != authority.environment_sha256
            or _runner_digest(plan, admission.inputs) != authority.runner_fingerprint
        ):
            _fail("producer_bundle_receipt_authority_mismatch")
        record = inspect_candidate_execution_record(
            run_root / "attempt", plan=plan, admission=admission,
            expected_admission_sha256=admission.digest(), expected_plan_sha256=plan.digest(),
            expected_bundle_sha256=bundle.digest(), expected_contract_sha256=authority.contract_sha256,
            expected_completion_sha256=result.execution.completion_sha256,
        )
        if record.to_dict() != result.execution.to_dict():
            _fail("producer_bundle_receipt_evidence_invalid")
        evaluation_entries = list((run_root / "evaluations").iterdir())
        if len(evaluation_entries) != 1 or evaluation_entries[0].is_symlink() or not evaluation_entries[0].is_dir():
            _fail("producer_bundle_receipt_evidence_invalid")
        saved_evaluation = inspect_candidate_evaluation(
            evaluation_entries[0], expected_evaluation_sha256=result.evaluation.digest(),
        )
        if saved_evaluation.to_dict() != result.evaluation.to_dict():
            _fail("producer_bundle_receipt_evidence_invalid")

        source_files: dict[str, bytes] = {}
        # The manifest is a native bundle sidecar rather than a declared source file, but the
        # final Candidate's bundle evidence points at it. Carry the exact retained bytes through
        # Feature 153 so a committed artifact remains independently revalidatable.
        bundle_manifest = _files.read_regular_file(
            source_root / "bundle-manifest.json", MAX_CANDIDATE_BUNDLE_BYTES,
        )
        try:
            saved_bundle = parse_candidate_source_bundle(strict_json(bundle_manifest))
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ProducerBundleReceiptError("producer_bundle_receipt_source_invalid") from exc
        if saved_bundle.digest() != result.bundle.digest():
            _fail("producer_bundle_receipt_source_invalid")
        for item in result.bundle.files:
            content = _files.read_regular_file(source_root / item.path, item.size, exact_size=True)
            if hashlib.sha256(content).hexdigest() != item.sha256:
                _fail("producer_bundle_receipt_source_invalid")
            source_files[item.path] = content
        entrypoint_bytes = source_files[entrypoint]
        bundle_evidence = validate_bundle_evidence_shape({
            "protocol": "lunar-population-bundle-v1",
            "bundle_sha256": result.bundle.digest(),
            "bundle_path": f"evolution/candidates/{candidate_id}/bundle-manifest.json",
            "source_root": f"evolution/candidates/{candidate_id}",
            "run_root": result.run_root.relative_to(root).as_posix(),
            "plan_sha256": result.plan.digest(),
            "admission_sha256": result.admission.digest(),
            "completion_sha256": result.execution.completion_sha256,
            "evaluation_path": result.evaluation.evaluation_path.relative_to(root).as_posix(),
            "evaluation_sha256": result.evaluation.digest(),
        })
        parent_id = result.parent_id
        generation = result.generation
        iteration = result.iteration
        island_id = result.island_id
        if any(value is None for value in (generation, iteration, island_id)):
            _fail("producer_bundle_receipt_lineage_invalid")
        source_sha256 = hashlib.sha256(entrypoint_bytes).hexdigest()
        receipt = CandidateReceipt.from_report(
            result.report, candidate_id=candidate_id, source_sha256=source_sha256,
            contract_sha256=authority.contract_sha256, evaluator_kind=authority.evaluator_kind,
            evaluator_fingerprint=authority.evaluator_fingerprint,
            dependency_sha256=authority.dependency_sha256,
            environment_sha256=authority.environment_sha256,
            runner_fingerprint=authority.runner_fingerprint,
            generator_fingerprint=authority.generator_fingerprint,
            parent_id=parent_id, generation=generation, iteration=iteration, island_id=island_id,
            execution_sha256=None, bundle_evidence=bundle_evidence,
        )
        integrity = {
            **authority.to_dict(), "candidate_id": candidate_id, "parent_id": parent_id,
            "generation": generation, "iteration": iteration, "island_id": island_id,
            "receipt_sha256": receipt.receipt_sha256, "source_sha256": source_sha256,
            "bundle_evidence_sha256": hashlib.sha256(
                _canonical(bundle_evidence)
            ).hexdigest(),
        }
        candidate = Candidate(
            candidate_id=candidate_id,
            code_path=f"evolution/candidates/{candidate_id}/{entrypoint}",
            parent_id=parent_id, generation=generation, iteration=iteration,
            strategy="population", island_id=island_id, evaluation=result.report,
            metadata=dict(result.metadata or {}), source_sha256=source_sha256,
            receipt_sha256=receipt.receipt_sha256, integrity=integrity,
            bundle_evidence=bundle_evidence,
        )
        execution = build_native_producer_bundle_execution_receipt(result, candidate_id=candidate_id)
        evaluation = build_native_producer_bundle_evaluation_receipt(result, candidate_id=candidate_id)
        binding_path = result.source_root.parent / "draft-binding.json"
        evidence_roots = (result.source_root, result.run_root, binding_path)
        if result.journal_sha256 is not None:
            from .producer_bundle_intent import verify_producer_bundle_prepared_intent
            from .producer_bundle_publication import parse_producer_bundle_publication_journal

            intent_path = root / "evolution" / "producer-batches" / result.journal_id / "journal.prepared.json"
            intent = parse_producer_bundle_publication_journal(intent_path)
            if intent.digest() != result.journal_sha256:
                _fail("producer_bundle_receipt_evidence_invalid")
            verify_producer_bundle_prepared_intent(root, intent)
            evidence_roots += (intent_path,)
        retained_evidence = _collect_retained_evidence(root, evidence_roots)
        return ProducerBundlePublicationArtifact(
            candidate_id=candidate_id, source_files=source_files,
            record=candidate.to_dict(), receipt=receipt.to_dict(),
            execution_receipt=execution.to_dict(), evaluation_receipt=evaluation.to_dict(),
            execution_receipt_sha256=execution.digest(), evaluation_receipt_sha256=evaluation.digest(),
            bundle_manifest=saved_bundle.to_dict(),
            retained_evidence=retained_evidence,
        )
    except ProducerBundleReceiptError:
        raise
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_artifact_invalid") from exc


def build_producer_bundle_publication_artifact(archive: Any, candidate: Candidate):
    """Adapt one persisted pipeline candidate to Feature 153's publication artifact.

    The archive and candidate are read only.  Execution/evaluation receipts are attached as
    dedicated sidecars by the staging layer; native record/receipt bytes remain unchanged.
    """
    from .bundle_evolution import read_candidate_source_files
    from .producer_bundle_staging import ProducerBundlePublicationArtifact

    try:
        execution = build_producer_bundle_execution_receipt(archive.workspace, candidate)
        evaluation = build_producer_bundle_evaluation_receipt(archive.workspace, candidate)
        sources = {name: content.encode("utf-8") for name, content in read_candidate_source_files(archive.workspace, candidate).items()}
        bundle_manifest_bytes = _files.read_regular_file(
            archive.workspace / candidate.bundle_evidence["bundle_path"], MAX_CANDIDATE_BUNDLE_BYTES,
        )
        try:
            bundle_manifest = parse_candidate_source_bundle(strict_json(bundle_manifest_bytes))
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ProducerBundleReceiptError("producer_bundle_receipt_source_invalid") from exc
        if bundle_manifest.digest() != candidate.bundle_evidence["bundle_sha256"]:
            _fail("producer_bundle_receipt_source_invalid")
        receipt = archive.read_candidate_receipt(candidate.candidate_id, source_path=archive.workspace / candidate.code_path)
        if receipt.candidate_id != candidate.candidate_id or receipt.receipt_sha256 != candidate.receipt_sha256:
            _fail("producer_bundle_receipt_candidate_invalid")
        retained_evidence = _collect_retained_evidence(
            _files.absolute_path(archive.workspace),
            (_files.absolute_path(archive.workspace / candidate.bundle_evidence["source_root"]),
             _files.absolute_path(archive.workspace / candidate.bundle_evidence["run_root"])),
        )
        return ProducerBundlePublicationArtifact(
            candidate_id=candidate.candidate_id, source_files=sources,
            record=candidate.to_dict(), receipt=receipt.to_dict(),
            execution_receipt=execution.to_dict(), evaluation_receipt=evaluation.to_dict(),
            execution_receipt_sha256=execution.digest(), evaluation_receipt_sha256=evaluation.digest(),
            bundle_manifest=bundle_manifest.to_dict(),
            retained_evidence=retained_evidence,
        )
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_artifact_invalid") from exc


__all__ = [
    "ProducerBundleEvaluationReceipt",
    "ProducerBundleExecutionReceipt",
    "ProducerBundleReceiptError",
    "build_native_producer_bundle_evaluation_receipt",
    "build_native_producer_bundle_execution_receipt",
    "build_native_producer_bundle_publication_artifact",
    "build_producer_bundle_evaluation_receipt",
    "build_producer_bundle_execution_receipt",
    "build_producer_bundle_publication_artifact",
    "verify_native_retained_evidence",
]
