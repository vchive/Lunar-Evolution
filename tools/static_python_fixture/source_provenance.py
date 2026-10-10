"""Pure comparison of archive receipt claims and detached source-tree evidence.

This preparation tool never acquires source, checks a signature, opens a path,
builds, launches, or admits a runtime.  Matching detached declarations is not
proof of the provenance or acquisition of their caller-supplied bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from .archive_observation import ArchiveSourceIdentity
from .source_tree_observation import (
    SOURCE_TREE_OBSERVATION_SCHEMA,
    SOURCE_TREE_SCHEMA,
    StaticPythonSourceTreeFile,
    StaticPythonSourceTreeObservation,
)
from .verified_inputs import (
    MAX_ARCHIVE_RECEIPT_BYTES,
    MAX_EXTRACTION_MANIFEST_BYTES,
    MAX_EXTRACTION_MEMBER_BYTES,
    MAX_EXTRACTION_MEMBERS,
    MAX_EXTRACTION_PATH_BYTES,
    MAX_EXTRACTION_PATH_SEGMENTS,
    MAX_EXTRACTION_TOTAL_BYTES,
    MAX_EXTRACTION_TOTAL_PATH_BYTES,
    StaticPythonArchiveReceipt,
    StaticPythonVerifiedInputError,
    validate_static_python_archive_receipt,
)

SOURCE_PROVENANCE_SCHEMA = "lunar-static-python-source-provenance-comparison-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SourceProvenanceComparisonError(ValueError):
    """Fixed refusals without receipt-controlled text, paths, or archive bytes."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,64}", reason) is None:
            reason = "invalid"
        self.reason = "source_provenance_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise SourceProvenanceComparisonError(reason)


def _pin(value: object, name: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(name + "_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SourceProvenanceComparisonError("canonical_invalid") from exc
    if len(raw) > MAX_EXTRACTION_MANIFEST_BYTES:
        _fail("canonical_bounds")
    return raw


def _integer(value: object, maximum: int, reason: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _identity(identity: object) -> dict[str, int] | None:
    if identity is None:
        return None
    if type(identity) is not ArchiveSourceIdentity:
        _fail("source_identity_invalid")
    result = {}
    for name in ("device", "inode", "size", "mode", "mtime_ns", "ctime_ns"):
        result[name] = _integer(getattr(identity, name), (1 << 64) - 1,
                                "source_identity_invalid")
    if result["mode"] > 0o777:
        _fail("source_identity_invalid")
    return result


def _file_wire(item: object, root: str) -> dict[str, object]:
    if type(item) is not StaticPythonSourceTreeFile:
        _fail("file_type_invalid")
    path = item.path
    if type(path) is not str or not path or len(path) > MAX_EXTRACTION_PATH_BYTES:
        _fail("file_path_invalid")
    try:
        path_bytes = path.encode("utf-8")
    except UnicodeError:
        _fail("file_path_invalid")
    parts = path.split("/")
    if (len(path_bytes) > MAX_EXTRACTION_PATH_BYTES or len(parts) > MAX_EXTRACTION_PATH_SEGMENTS
            or not path.startswith(root + "/") or "\\" in path or ":" in path
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in path)):
        _fail("file_path_invalid")
    mode = _integer(item.mode, 0o777, "file_mode_invalid")
    size = _integer(item.size, MAX_EXTRACTION_MEMBER_BYTES, "file_size_invalid")
    _pin(item.sha256, "file_digest")
    return {"path": path, "mode": mode, "size": size, "sha256": item.sha256}


def _observation(
    value: StaticPythonSourceTreeObservation,
    receipt: StaticPythonArchiveReceipt,
) -> tuple[dict[str, object], tuple[StaticPythonSourceTreeFile, ...]]:
    if type(value) is not StaticPythonSourceTreeObservation:
        _fail("observation_type_invalid")
    for name in ("tree_json", "canonical_json"):
        raw = getattr(value, name)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EXTRACTION_MANIFEST_BYTES:
            _fail("observation_wire_invalid")
    for name in ("schema", "archive", "root", "version", "metadata_validation",
                 "signature_verification"):
        text = getattr(value, name)
        if type(text) is not str or not text or len(text) > 128:
            _fail("observation_text_invalid")
    if value.schema != SOURCE_TREE_OBSERVATION_SCHEMA:
        _fail("observation_schema_invalid")
    if any(type(getattr(value, name)) is not bool
           for name in ("profile_pin_verified", "source_preimages_checked")):
        _fail("observation_status_invalid")
    for name in ("archive_sha256", "snapshot_sha256", "manifest_sha256",
                 "source_tree_sha256", "observation_sha256"):
        _pin(getattr(value, name), "observation_digest")
    identity = _identity(value.source_identity)
    if type(value.files) is not tuple or not 1 <= len(value.files) <= MAX_EXTRACTION_MEMBERS:
        _fail("observation_files_invalid")
    files = [_file_wire(item, value.root) for item in value.files]
    paths = [item["path"] for item in files]
    if paths != sorted(set(paths)):
        _fail("file_order_invalid")
    path_set = set(paths)
    if any("/".join(path.split("/")[:index]) in path_set
           for path in paths for index in range(1, len(path.split("/")))):
        _fail("file_ancestor_invalid")
    if sum(len(path.encode("utf-8")) for path in paths) > MAX_EXTRACTION_TOTAL_PATH_BYTES:
        _fail("file_path_bounds")
    total = _integer(value.total_bytes, MAX_EXTRACTION_TOTAL_BYTES, "total_bytes_invalid")
    if sum(item["size"] for item in files) != total:
        _fail("total_bytes_mismatch")
    tree = {"schema": SOURCE_TREE_SCHEMA, "archive": value.archive, "root": value.root,
            "version": value.version, "files": files}
    if _canonical(tree) != value.tree_json:
        _fail("tree_canonical_mismatch")
    if hashlib.sha256(value.tree_json).hexdigest() != value.source_tree_sha256:
        _fail("tree_digest_mismatch")
    record = {
        "schema": value.schema, "archive": value.archive, "root": value.root,
        "version": value.version, "archive_sha256": value.archive_sha256,
        "snapshot_sha256": value.snapshot_sha256, "manifest_sha256": value.manifest_sha256,
        "source_tree_sha256": value.source_tree_sha256,
        "profile_pin_verified": value.profile_pin_verified,
        "metadata_validation": value.metadata_validation,
        "source_preimages_checked": value.source_preimages_checked,
        "signature_verification": value.signature_verification,
        "source_identity": identity, "total_bytes": total, "files": files,
    }
    if _canonical(record) != value.canonical_json:
        _fail("observation_canonical_mismatch")
    if hashlib.sha256(value.canonical_json).hexdigest() != value.observation_sha256:
        _fail("observation_digest_mismatch")
    if value.snapshot_sha256 != value.archive_sha256:
        _fail("snapshot_archive_mismatch")
    if value.profile_pin_verified is not True or value.metadata_validation != "validated":
        _fail("observation_inert_or_unknown")
    if value.signature_verification != "not-performed":
        _fail("observation_signature_invalid")
    if identity is None:
        _fail("source_identity_invalid")
    if receipt.archive != "cpython" or (
            receipt.archive, receipt.root, receipt.version, receipt.sha256, receipt.size
    ) != (value.archive, value.root, value.version, value.archive_sha256, identity["size"]):
        _fail("receipt_observation_mismatch")
    return record, tuple(StaticPythonSourceTreeFile(**item) for item in files)


@dataclass(frozen=True, slots=True)
class SourceProvenanceComparison:
    """Deeply frozen agreement evidence; no build, signature or runtime authority."""

    schema: str
    receipt_sha256: str
    observation_sha256: str
    manifest_sha256: str
    source_tree_sha256: str
    files: tuple[StaticPythonSourceTreeFile, ...]
    total_bytes: int
    declared_signature_verification: str
    observed_signature_verification: str
    signature_verification_performed: bool
    execution_performed: bool
    runtime_load_protection: bool
    production_admission: bool
    general_code_origin_protection: bool
    canonical_bytes: bytes
    comparison_sha256: str

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.canonical_bytes)

    def to_json(self) -> bytes:
        return self.canonical_bytes


def compare_source_provenance(
    receipt_raw: bytes,
    observation: StaticPythonSourceTreeObservation,
    *,
    expected_receipt_sha256: str,
    expected_manifest_sha256: str,
    expected_source_tree_sha256: str,
) -> SourceProvenanceComparison:
    """Compare the existing archive receipt with coherent fixed-profile tree evidence.

    A successful comparison records consistency of detached inputs only. It does
    not establish that the supplied DTO was acquired by the archive observer.
    """
    _pin(expected_receipt_sha256, "receipt_pin")
    _pin(expected_manifest_sha256, "manifest_pin")
    _pin(expected_source_tree_sha256, "source_tree_pin")
    if type(receipt_raw) is not bytes or not 0 < len(receipt_raw) <= MAX_ARCHIVE_RECEIPT_BYTES:
        _fail("receipt_wire_invalid")
    try:
        receipt = validate_static_python_archive_receipt(
            receipt_raw, expected_sha256=expected_receipt_sha256,
        )
    except StaticPythonVerifiedInputError as exc:
        reason = exc.reason.removeprefix("static_python_verified_input_")
        raise SourceProvenanceComparisonError("receipt_" + reason) from exc
    record, files = _observation(observation, receipt)
    if record["manifest_sha256"] != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    if record["source_tree_sha256"] != expected_source_tree_sha256:
        _fail("source_tree_pin_mismatch")
    result_record = {
        "schema": SOURCE_PROVENANCE_SCHEMA, "receipt_sha256": receipt.receipt_sha256,
        "observation_sha256": observation.observation_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "source_tree_sha256": expected_source_tree_sha256,
        "archive": receipt.archive, "root": receipt.root, "version": receipt.version,
        "archive_sha256": receipt.sha256, "archive_size": receipt.size,
        "profile_pin_verified": True, "metadata_validation": "validated",
        "source_preimages_checked": observation.source_preimages_checked,
        "files": record["files"], "total_bytes": observation.total_bytes,
        "declared_signature_verification": receipt.signature_verification,
        "observed_signature_verification": observation.signature_verification,
        "signature_verification_performed": False, "execution_performed": False,
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }
    canonical = _canonical(result_record)
    return SourceProvenanceComparison(
        schema=SOURCE_PROVENANCE_SCHEMA, receipt_sha256=receipt.receipt_sha256,
        observation_sha256=observation.observation_sha256,
        manifest_sha256=expected_manifest_sha256, source_tree_sha256=expected_source_tree_sha256,
        files=files, total_bytes=observation.total_bytes,
        declared_signature_verification=receipt.signature_verification,
        observed_signature_verification=observation.signature_verification,
        signature_verification_performed=False, execution_performed=False,
        runtime_load_protection=False, production_admission=False,
        general_code_origin_protection=False, canonical_bytes=canonical,
        comparison_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "SOURCE_PROVENANCE_SCHEMA",
    "SourceProvenanceComparison",
    "SourceProvenanceComparisonError",
    "compare_source_provenance",
]
