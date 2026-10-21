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
from itertools import chain
from typing import NoReturn

from . import source_patches
from .archive_observation import ArchiveSourceIdentity
from .source_staging import (
    MAX_SOURCE_STAGING_JSON_TEXT_BYTES,
    MAX_SOURCE_STAGING_MANIFEST_BYTES,
    MAX_SOURCE_STAGING_PATH_BYTES,
    MAX_STAGED_ENTRIES,
    SOURCE_STAGING_SCHEMA,
    StaticPythonSourceStaging,
)
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
_STAGING_MANIFEST_FIELDS = frozenset({
    "schema", "destination", "root", "root_directory", "archive", "archive_sha256",
    "snapshot_sha256", "manifest_sha256", "projection_sha256", "policy_sha256",
    "patch_set_sha256", "profile_pin_verified", "metadata_validation",
    "source_preimages_checked", "signature_verification", "tree_identity",
    "ancestor_identities", "entries", "extraction_performed", "fixed_patches_staged",
    "release_verified", "source_execution_performed", "build_performed",
    "frozen_headers_generated", "runtime_execution_performed", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
})
_STAGING_FILE_FIELDS = frozenset({
    "path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode",
    "device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns",
})
_STAGING_DIRECTORY_FIELDS = frozenset({
    "path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode",
    "device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_STAGING_JSON_NODES = 4_500_000


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


def _canonical(value: object, *, maximum: int = MAX_EXTRACTION_MANIFEST_BYTES) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SourceProvenanceComparisonError("canonical_invalid") from exc
    if len(raw) > maximum:
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


def _json_constant(_: str) -> NoReturn:
    _fail("staging_json_invalid")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("staging_duplicate_key")
        result[key] = value
    return result


def _scan_json(value: object, *, max_string_bytes: int = MAX_EXTRACTION_MANIFEST_BYTES) -> None:
    nodes = text_bytes = 0
    pending = [(iter((value,)), 0)]
    while pending:
        iterator, depth = pending[-1]
        try:
            item = next(iterator)
        except StopIteration:
            pending.pop()
            continue
        nodes += 1
        if nodes > _MAX_STAGING_JSON_NODES or depth > 16:
            _fail("staging_bounds_invalid")
        if type(item) is dict:
            if len(item) > 131_072:
                _fail("staging_bounds_invalid")
            pending.append((chain(item.keys(), item.values()), depth + 1))
        elif type(item) is list:
            if len(item) > 131_072:
                _fail("staging_bounds_invalid")
            pending.append((iter(item), depth + 1))
        elif type(item) is str:
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                _fail("staging_json_invalid")
            if text_bytes > max_string_bytes:
                _fail("staging_bounds_invalid")
        elif type(item) not in (int, bool, type(None)):
            _fail("staging_json_invalid")


def _canonical_wire(raw: bytes, reason: str) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_STAGING_MANIFEST_BYTES:
        _fail(reason + "_wire_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_json_constant, parse_constant=_json_constant)
        _scan_json(value, max_string_bytes=MAX_SOURCE_STAGING_JSON_TEXT_BYTES)
        canonical = _canonical(value, maximum=MAX_SOURCE_STAGING_MANIFEST_BYTES)
    except SourceProvenanceComparisonError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise SourceProvenanceComparisonError(reason + "_json_invalid") from exc
    if type(value) is not dict or canonical != raw:
        _fail(reason + "_canonical_invalid")
    return value


def _text(value: object, maximum: int, reason: str) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        _fail(reason)
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail(reason)
    except UnicodeError:
        _fail(reason)
    return value


def _archive_path(value: object, root: str, *, directory: bool = False) -> str:
    if type(value) is not str or not value or len(value) > MAX_EXTRACTION_PATH_BYTES:
        _fail("staging_path_invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        _fail("staging_path_invalid")
    parts = value.split("/")
    if (len(encoded) > MAX_EXTRACTION_PATH_BYTES or len(parts) > MAX_EXTRACTION_PATH_SEGMENTS
            or (value != root and not value.startswith(root + "/"))
            or "\\" in value or ":" in value
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value)
            or not directory and value == root):
        _fail("staging_path_invalid")
    return value


def _stat_integer(value: object, name: str, *, signed: bool = False,
                  minimum: int = 0) -> int:
    low = -(1 << 63) if signed else minimum
    high = (1 << 63) - 1 if signed else (1 << 64) - 1
    if type(value) is not int or not low <= value <= high:
        _fail("staging_stat_invalid")
    return value


def _validate_tree_observation(
    observation: StaticPythonSourceTreeObservation,
) -> tuple[dict[str, object], tuple[StaticPythonSourceTreeFile, ...]]:
    if type(observation) is not StaticPythonSourceTreeObservation:
        _fail("observation_type_invalid")
    for name in ("tree_json", "canonical_json"):
        raw = getattr(observation, name)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_EXTRACTION_MANIFEST_BYTES:
            _fail("observation_wire_invalid")
    for name in ("schema", "archive", "root", "version", "metadata_validation",
                 "signature_verification"):
        _text(getattr(observation, name), 128, "observation_text_invalid")
    if observation.schema != SOURCE_TREE_OBSERVATION_SCHEMA:
        _fail("observation_schema_invalid")
    if any(type(getattr(observation, name)) is not bool
           for name in ("profile_pin_verified", "source_preimages_checked")):
        _fail("observation_status_invalid")
    for name in ("archive_sha256", "snapshot_sha256", "manifest_sha256",
                 "source_tree_sha256", "observation_sha256"):
        _pin(getattr(observation, name), "observation_digest")
    identity = _identity(observation.source_identity)
    if type(observation.files) is not tuple or not 1 <= len(observation.files) <= MAX_EXTRACTION_MEMBERS:
        _fail("observation_files_invalid")
    files = tuple(_file_wire(item, observation.root) for item in observation.files)
    paths = [item["path"] for item in files]
    if paths != sorted(set(paths)):
        _fail("observation_file_order_invalid")
    path_set = set(paths)
    if any("/".join(path.split("/")[:index]) in path_set
           for path in paths for index in range(1, len(path.split("/")))):
        _fail("observation_file_ancestor_invalid")
    path_bytes = sum(len(path.encode("utf-8")) for path in paths)
    if path_bytes > MAX_EXTRACTION_TOTAL_PATH_BYTES:
        _fail("observation_path_bounds_invalid")
    total = _integer(observation.total_bytes, MAX_EXTRACTION_TOTAL_BYTES,
                     "observation_total_bytes_invalid")
    if sum(item["size"] for item in files) != total:
        _fail("observation_total_bytes_mismatch")
    tree = {"schema": SOURCE_TREE_SCHEMA, "archive": observation.archive,
            "root": observation.root, "version": observation.version, "files": list(files)}
    tree_raw = _canonical(tree)
    if tree_raw != observation.tree_json:
        _fail("observation_tree_canonical_mismatch")
    if hashlib.sha256(tree_raw).hexdigest() != observation.source_tree_sha256:
        _fail("observation_tree_digest_mismatch")
    if observation.snapshot_sha256 != observation.archive_sha256:
        _fail("observation_snapshot_archive_mismatch")
    if observation.signature_verification != "not-performed":
        _fail("observation_signature_invalid")
    profile_state = (observation.profile_pin_verified, observation.metadata_validation)
    if profile_state not in ((True, "validated"), (False, "skipped-inert-profile")):
        _fail("observation_metadata_invalid")
    if observation.archive != "cpython":
        _fail("observation_archive_invalid")
    if observation.profile_pin_verified and identity is None:
        _fail("observation_source_identity_invalid")
    record = {
        "schema": observation.schema, "archive": observation.archive,
        "root": observation.root, "version": observation.version,
        "archive_sha256": observation.archive_sha256,
        "snapshot_sha256": observation.snapshot_sha256,
        "manifest_sha256": observation.manifest_sha256,
        "source_tree_sha256": observation.source_tree_sha256,
        "profile_pin_verified": observation.profile_pin_verified,
        "metadata_validation": observation.metadata_validation,
        "source_preimages_checked": observation.source_preimages_checked,
        "signature_verification": observation.signature_verification,
        "source_identity": identity, "total_bytes": total,
        "files": list(files),
    }
    canonical = _canonical(record)
    if canonical != observation.canonical_json:
        _fail("observation_canonical_mismatch")
    if hashlib.sha256(canonical).hexdigest() != observation.observation_sha256:
        _fail("observation_digest_mismatch")
    return record, files


def _destination(value: object) -> str:
    text = _text(value, 4096, "staging_destination_invalid")
    if not text.startswith("/") or "\\" in text or "\0" in text:
        _fail("staging_destination_invalid")
    parts = text[1:].split("/")
    if (not parts or len(parts) > 64
            or any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255
                   for part in parts)):
        _fail("staging_destination_invalid")
    return text


def _validate_stat_wire(item: dict[str, object], *, directory: bool) -> None:
    _stat_integer(item["device"], "device")
    _stat_integer(item["inode"], "inode")
    mode = _stat_integer(item["mode"], "mode")
    nlink = _stat_integer(item["nlink"], "nlink", minimum=1)
    _stat_integer(item["size"], "size")
    _stat_integer(item["mtime_ns"], "mtime", signed=True)
    _stat_integer(item["ctime_ns"], "ctime", signed=True)
    if directory:
        if mode != 0o700 or nlink < 1:
            _fail("staging_stat_invalid")
    elif mode != 0o600 or nlink != 1:
        _fail("staging_stat_invalid")


def _validate_tree_identity(value: object) -> None:
    expected = frozenset({"device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns"})
    if type(value) is not dict or frozenset(value) != expected:
        _fail("staging_tree_identity_invalid")
    _stat_integer(value["device"], "device")
    _stat_integer(value["inode"], "inode")
    raw_mode = _stat_integer(value["raw_mode"], "mode")
    _stat_integer(value["nlink"], "nlink", minimum=1)
    _stat_integer(value["size"], "size")
    _stat_integer(value["mtime_ns"], "mtime", signed=True)
    _stat_integer(value["ctime_ns"], "ctime", signed=True)
    if raw_mode != 0o40700:
        _fail("staging_tree_identity_invalid")


def _validate_staging_manifest(
    staging: StaticPythonSourceStaging,
    expected_staging_sha256: str,
) -> dict[str, object]:
    if type(staging) is not StaticPythonSourceStaging:
        _fail("staging_type_invalid")
    for name in ("schema", "destination", "root_directory"):
        _text(getattr(staging, name), 4096, "staging_dto_invalid")
    if staging.schema != SOURCE_STAGING_SCHEMA:
        _fail("staging_schema_invalid")
    _pin(staging.staging_sha256, "staging_digest")
    if staging.staging_sha256 != expected_staging_sha256:
        _fail("staging_pin_mismatch")
    raw = staging.canonical_json
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_STAGING_MANIFEST_BYTES:
        _fail("staging_wire_invalid")
    if hashlib.sha256(raw).hexdigest() != staging.staging_sha256:
        _fail("staging_digest_mismatch")
    manifest = _canonical_wire(raw, "staging")
    if frozenset(manifest) != _STAGING_MANIFEST_FIELDS:
        _fail("staging_schema_invalid")
    if manifest["schema"] != SOURCE_STAGING_SCHEMA:
        _fail("staging_schema_invalid")
    destination = _destination(staging.destination)
    root = _text(manifest["root"], MAX_EXTRACTION_PATH_BYTES, "staging_root_invalid")
    if (manifest["destination"] != destination
            or staging.root_directory != destination + "/" + root
            or manifest["root_directory"] != staging.root_directory):
        _fail("staging_dto_mismatch")
    for name in ("archive_sha256", "snapshot_sha256", "manifest_sha256", "projection_sha256",
                 "policy_sha256", "patch_set_sha256"):
        _pin(manifest[name], "staging_" + name.removesuffix("_sha256"))
    if type(manifest["archive"]) is not str or type(manifest["signature_verification"]) is not str:
        _fail("staging_status_invalid")
    bool_fields = (
        "profile_pin_verified", "source_preimages_checked", "extraction_performed",
        "fixed_patches_staged", "release_verified", "source_execution_performed",
        "build_performed", "frozen_headers_generated", "runtime_execution_performed",
        "runtime_load_protection", "production_admission", "general_code_origin_protection",
    )
    for name in bool_fields:
        if type(manifest[name]) is not bool:
            _fail("staging_status_invalid")
    for name in ("extraction_performed", "fixed_patches_staged", "source_preimages_checked"):
        if manifest[name] is not True:
            _fail("staging_claim_invalid")
    for name in ("release_verified", "source_execution_performed", "build_performed",
                 "frozen_headers_generated", "runtime_execution_performed",
                 "runtime_load_protection", "production_admission",
                 "general_code_origin_protection"):
        if manifest[name] is not False:
            _fail("staging_claim_invalid")
    dto_flags = (
        ("extraction_performed", "extraction_performed"),
        ("fixed_patches_staged", "fixed_patches_staged"),
        ("release_verified", "release_verified"),
        ("source_execution_performed", "source_execution_performed"),
        ("build_performed", "build_performed"),
        ("frozen_headers_generated", "frozen_headers_generated"),
        ("runtime_execution_performed", "runtime_execution_performed"),
        ("runtime_load_protection", "runtime_load_protection"),
        ("production_admission", "production_admission"),
        ("general_code_origin_protection", "general_code_origin_protection"),
    )
    for attribute, wire in dto_flags:
        value = getattr(staging, attribute)
        if type(value) is not bool or value is not manifest[wire]:
            _fail("staging_dto_mismatch")
    if type(manifest["metadata_validation"]) is not str:
        _fail("staging_status_invalid")
    state = (manifest["profile_pin_verified"], manifest["metadata_validation"])
    if state not in ((True, "validated"), (False, "skipped-inert-profile")):
        _fail("staging_metadata_invalid")
    if manifest["signature_verification"] != "not-performed":
        _fail("staging_signature_invalid")
    _validate_tree_identity(manifest["tree_identity"])
    ancestors = manifest["ancestor_identities"]
    if (type(ancestors) is not list or len(ancestors) != len(destination[1:].split("/"))
            or not 1 <= len(ancestors) <= 64):
        _fail("staging_ancestor_identity_invalid")
    for item in ancestors:
        if type(item) is not dict or frozenset(item) != frozenset({"device", "inode"}):
            _fail("staging_ancestor_identity_invalid")
        _stat_integer(item["device"], "device")
        _stat_integer(item["inode"], "inode")
    return manifest


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


def validate_source_staging_consistency(
    observation: StaticPythonSourceTreeObservation,
    staging: StaticPythonSourceStaging,
    *,
    expected_staging_sha256: str,
    expected_manifest_sha256: str,
    expected_source_tree_sha256: str,
) -> None:
    """Refuse unless detached source-tree and staging DTOs agree exactly.

    This checks internal consistency only. It does not reopen the staged path,
    prove either DTO was honestly produced, or authorize a build/runtime.
    ``None`` means the supplied bounded records agree; all disagreement raises
    :class:`SourceProvenanceComparisonError` with a fixed reason.
    """
    _pin(expected_staging_sha256, "staging_pin")
    _pin(expected_manifest_sha256, "manifest_pin")
    _pin(expected_source_tree_sha256, "source_tree_pin")
    observation_record, observed_files = _validate_tree_observation(observation)
    if observation_record["manifest_sha256"] != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    if observation_record["source_tree_sha256"] != expected_source_tree_sha256:
        _fail("source_tree_pin_mismatch")

    manifest = _validate_staging_manifest(staging, expected_staging_sha256)
    if manifest["manifest_sha256"] != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    if (manifest["archive"] != observation.archive
            or manifest["root"] != observation.root
            or manifest["archive_sha256"] != observation.archive_sha256
            or manifest["snapshot_sha256"] != observation.snapshot_sha256):
        _fail("archive_observation_mismatch")

    policy = source_patches.source_patch_manifest()
    version = policy["source_version"]
    if (type(version) is not str or observation.version != version
            or observation.root != "Python-" + version):
        _fail("version_root_mismatch")
    if manifest["patch_set_sha256"] != policy["patch_set_sha256"]:
        _fail("patch_set_mismatch")
    expected_policy_sha256 = hashlib.sha256(_canonical(policy)).hexdigest()
    if manifest["policy_sha256"] != expected_policy_sha256:
        _fail("patch_policy_mismatch")

    observation_state = (observation.profile_pin_verified, observation.metadata_validation)
    staging_state = (manifest["profile_pin_verified"], manifest["metadata_validation"])
    if observation_state != staging_state:
        _fail("profile_state_mismatch")

    patch_by_path: dict[str, dict[str, object]] = {}
    for patch in policy["files"]:
        if type(patch) is not dict:
            _fail("patch_policy_invalid")
        relative = patch.get("path")
        if type(relative) is not str:
            _fail("patch_policy_invalid")
        patch_by_path[observation.root + "/" + relative] = patch

    entries = manifest["entries"]
    if type(entries) is not list or not 1 <= len(entries) <= MAX_STAGED_ENTRIES:
        _fail("staging_entries_invalid")
    paths: list[str] = []
    total_path_bytes = 0
    files_by_path: dict[str, dict[str, object]] = {}
    directories_by_path: dict[str, dict[str, object]] = {}
    for entry in entries:
        if type(entry) is not dict:
            _fail("staging_entry_invalid")
        kind = entry.get("kind")
        if type(kind) is not str or kind not in {"file", "directory"}:
            _fail("staging_entry_invalid")
        if frozenset(entry) != (_STAGING_FILE_FIELDS if kind == "file"
                                else _STAGING_DIRECTORY_FIELDS):
            _fail("staging_entry_invalid")
        path = _archive_path(entry["path"], observation.root, directory=kind == "directory")
        paths.append(path)
        total_path_bytes += len(path.encode("utf-8"))
        if total_path_bytes > MAX_SOURCE_STAGING_PATH_BYTES:
            _fail("staging_path_bounds_invalid")
        if len(path.split("/")) > MAX_EXTRACTION_PATH_SEGMENTS:
            _fail("staging_path_invalid")
        if type(entry["implicit"]) is not bool:
            _fail("staging_entry_invalid")
        _validate_stat_wire(entry, directory=kind == "directory")
        archive_mode = entry["archive_mode"]
        if kind == "file":
            if entry["implicit"] is not False:
                _fail("staging_file_invalid")
            if type(archive_mode) is not int or not 0 <= archive_mode <= 0o777:
                _fail("staging_archive_mode_invalid")
            _pin(entry["source_sha256"], "staging_source_digest")
            _pin(entry["staged_sha256"], "staging_postimage_digest")
            files_by_path[path] = entry
        else:
            if entry["source_sha256"] is not None or entry["staged_sha256"] is not None:
                _fail("staging_directory_invalid")
            if entry["implicit"]:
                if archive_mode is not None:
                    _fail("staging_directory_invalid")
            elif type(archive_mode) is not int or not 0 <= archive_mode <= 0o777:
                _fail("staging_archive_mode_invalid")
            directories_by_path[path] = entry
    if paths != sorted(set(paths)):
        _fail("staging_entry_order_invalid")

    observed_by_path = {item.path: item for item in observation.files}
    if set(files_by_path) != set(observed_by_path):
        _fail("staging_file_inventory_mismatch")
    required_directories: set[str] = set()
    for path in set(files_by_path) | set(directories_by_path):
        parent = path.rpartition("/")[0]
        while parent:
            required_directories.add(parent)
            parent = parent.rpartition("/")[0]
    if not required_directories.issubset(directories_by_path):
        _fail("staging_directory_inventory_mismatch")
    for path, entry in directories_by_path.items():
        if entry["implicit"] and path not in required_directories:
            _fail("staging_implicit_directory_invalid")

    source_tree_files: list[dict[str, object]] = []
    total_source_bytes = 0
    for item in observed_files:
        entry = files_by_path[item["path"]]
        patch = patch_by_path.get(item["path"])
        if (entry["archive_mode"] != item["mode"]
                or entry["source_sha256"] != item["sha256"]):
            _fail("staging_source_file_mismatch")
        if patch is None:
            source_size = item["size"]
            staged_size = item["size"]
            staged_sha = item["sha256"]
        else:
            source_size = patch["before_size"]
            staged_size = patch["after_size"]
            staged_sha = patch["after_sha256"]
            if (item["size"] != source_size or item["sha256"] != patch["before_sha256"]):
                _fail("staging_patch_preimage_mismatch")
        if (entry["size"] != staged_size or entry["staged_sha256"] != staged_sha):
            _fail("staging_postimage_mismatch")
        source_tree_files.append({
            "path": item["path"], "mode": item["mode"],
            "size": source_size, "sha256": item["sha256"],
        })
        total_source_bytes += source_size
    if total_source_bytes != observation.total_bytes:
        _fail("staging_source_total_mismatch")
    if set(patch_by_path) - set(observed_by_path):
        _fail("staging_patch_inventory_mismatch")

    source_tree = {
        "schema": SOURCE_TREE_SCHEMA, "archive": observation.archive,
        "root": manifest["root"], "version": version, "files": source_tree_files,
    }
    source_tree_raw = _canonical(source_tree)
    reconstructed_sha256 = hashlib.sha256(source_tree_raw).hexdigest()
    if reconstructed_sha256 != expected_source_tree_sha256:
        _fail("staging_source_tree_pin_mismatch")
    if reconstructed_sha256 != observation.source_tree_sha256:
        _fail("staging_source_tree_mismatch")


__all__ = [
    "SOURCE_PROVENANCE_SCHEMA",
    "SourceProvenanceComparison",
    "SourceProvenanceComparisonError",
    "compare_source_provenance",
    "validate_source_staging_consistency",
]
