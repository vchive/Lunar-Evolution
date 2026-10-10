"""Pure receipt-to-source-tree provenance comparison.

The comparator consumes a caller-retained canonical receipt and one detached
source-tree observation.  It does not open paths, acquire source, run tools,
or turn an inert fixture into release or production evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from tools.static_python_fixture.source_tree_observation import (
    StaticPythonSourceTreeFile,
    StaticPythonSourceTreeObservation,
)

SOURCE_PROVENANCE_SCHEMA = "lunar-static-python-source-provenance-v1"
MAX_RECEIPT_BYTES = 256 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_FIELDS = {
    "schema", "archive", "root", "version", "manifest_sha256",
    "source_tree_sha256", "profile_pin_verified", "metadata_validation",
    "source_preimages_checked", "signature_verification", "total_bytes", "files",
}
_FILE_FIELDS = {"path", "mode", "size", "sha256"}


class SourceProvenanceComparisonError(ValueError):
    """A fixed refusal code without paths, receipt bytes, or caller text."""

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
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SourceProvenanceComparisonError("canonical_invalid") from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("receipt_duplicate_key")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    _fail("receipt_json")


def _scan(value: object) -> None:
    nodes = text_bytes = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 8192 or depth > 12:
            _fail("receipt_bounds")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                text_bytes += len(item.encode("utf-8"))
            except UnicodeError:
                _fail("receipt_text")
            if text_bytes > MAX_RECEIPT_BYTES:
                _fail("receipt_bounds")
        elif type(item) not in (int, bool) and item is not None:
            _fail("receipt_json_type")


def _sha(value: object, reason: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _file(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _FILE_FIELDS:
        _fail("receipt_file_schema")
    path, mode, size, digest = value["path"], value["mode"], value["size"], value["sha256"]
    if type(path) is not str or not path or "\\" in path or any(
            part in {"", ".", ".."} for part in path.split("/")):
        _fail("receipt_file_path")
    if type(mode) is not int or not 0 <= mode <= 0o777:
        _fail("receipt_file_mode")
    if type(size) is not int or not 0 <= size <= 1 << 30:
        _fail("receipt_file_size")
    _sha(digest, "receipt_file_digest")
    return value


def _receipt(raw: bytes, expected_sha256: str) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECEIPT_BYTES:
        _fail("receipt_wire")
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
        )
    except SourceProvenanceComparisonError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _fail("receipt_json")
    _scan(payload)
    if type(payload) is not dict or set(payload) != _RECEIPT_FIELDS:
        _fail("receipt_schema")
    if _canonical(payload) != raw:
        _fail("receipt_canonical")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("receipt_pin_mismatch")
    if payload["schema"] != SOURCE_PROVENANCE_SCHEMA:
        _fail("receipt_schema")
    if any(
        type(payload[name]) is not str or not payload[name]
        for name in ("archive", "root", "version")
    ):
        _fail("receipt_text")
    _sha(payload["manifest_sha256"], "receipt_manifest_digest")
    _sha(payload["source_tree_sha256"], "receipt_tree_digest")
    if payload["profile_pin_verified"] is not True:
        _fail("receipt_inert")
    if payload["metadata_validation"] != "validated":
        _fail("receipt_metadata")
    if payload["signature_verification"] != "not-performed":
        _fail("receipt_signature")
    if type(payload["source_preimages_checked"]) is not bool:
        _fail("receipt_source_preimages")
    if type(payload["total_bytes"]) is not int or not 0 <= payload["total_bytes"] <= 1 << 40:
        _fail("receipt_total_bytes")
    files = payload["files"]
    if type(files) is not list or len(files) > 8192:
        _fail("receipt_files")
    for item in files:
        _file(item)
    paths = [item["path"] for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        _fail("receipt_file_order")
    return payload


def _observation_wire(observation: StaticPythonSourceTreeObservation) -> dict[str, object]:
    if type(observation) is not StaticPythonSourceTreeObservation:
        _fail("observation_type")
    if observation.profile_pin_verified is not True:
        _fail("observation_inert")
    if observation.metadata_validation != "validated":
        _fail("observation_metadata")
    if observation.signature_verification != "not-performed":
        _fail("observation_signature")
    if type(observation.source_preimages_checked) is not bool:
        _fail("observation_source_preimages")
    _sha(observation.manifest_sha256, "observation_manifest_digest")
    _sha(observation.source_tree_sha256, "observation_tree_digest")
    if type(observation.archive) is not str or type(observation.root) is not str \
            or type(observation.version) is not str:
        _fail("observation_text")
    try:
        tree = observation.to_tree()
    except Exception as exc:
        raise SourceProvenanceComparisonError("observation_tree_invalid") from exc
    if type(tree) is not dict or set(tree) != {"schema", "archive", "root", "version", "files"}:
        _fail("observation_tree_schema")
    files = tree["files"]
    if type(files) is not list:
        _fail("observation_files")
    expected_files: list[dict[str, object]] = []
    total = 0
    for item in observation.files:
        if type(item) is not StaticPythonSourceTreeFile:
            _fail("observation_file_type")
        if type(item.path) is not str or type(item.mode) is not int or type(item.size) is not int:
            _fail("observation_file_type")
        _sha(item.sha256, "observation_file_digest")
        total += item.size
        expected_files.append({"path": item.path, "mode": item.mode,
                               "size": item.size, "sha256": item.sha256})
    if tree != {"schema": "lunar-static-python-source-tree-v1", "archive": observation.archive,
                "root": observation.root, "version": observation.version,
                "files": expected_files}:
        _fail("observation_tree_mismatch")
    if total != observation.total_bytes:
        _fail("observation_total_bytes")
    if hashlib.sha256(_canonical(tree)).hexdigest() != observation.source_tree_sha256:
        _fail("observation_tree_digest")
    return {
        "schema": SOURCE_PROVENANCE_SCHEMA,
        "archive": observation.archive,
        "root": observation.root,
        "version": observation.version,
        "manifest_sha256": observation.manifest_sha256,
        "source_tree_sha256": observation.source_tree_sha256,
        "profile_pin_verified": observation.profile_pin_verified,
        "metadata_validation": observation.metadata_validation,
        "source_preimages_checked": observation.source_preimages_checked,
        "signature_verification": observation.signature_verification,
        "total_bytes": observation.total_bytes,
        "files": files,
    }


@dataclass(frozen=True, slots=True)
class SourceProvenanceComparison:
    """Detached receipt/tree agreement; it confers no build or runtime authority."""

    schema: str
    receipt_sha256: str
    manifest_sha256: str
    source_tree_sha256: str
    total_bytes: int
    files: tuple[dict[str, object], ...]
    profile_pin_verified: bool
    signature_verification: str
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
    """Compare one canonical G1 receipt with one fixed-profile observation."""
    _pin(expected_receipt_sha256, "receipt_pin")
    _pin(expected_manifest_sha256, "manifest_pin")
    _pin(expected_source_tree_sha256, "source_tree_pin")
    payload = _receipt(receipt_raw, expected_receipt_sha256)
    observed = _observation_wire(observation)
    if observation.manifest_sha256 != expected_manifest_sha256:
        _fail("manifest_pin_mismatch")
    if observation.source_tree_sha256 != expected_source_tree_sha256:
        _fail("source_tree_pin_mismatch")
    if observation.manifest_sha256 != payload["manifest_sha256"]:
        _fail("manifest_mismatch")
    if observation.source_tree_sha256 != payload["source_tree_sha256"]:
        _fail("source_tree_mismatch")
    # Compare every receipt field, including status and complete regular-file wire.
    if observed != payload:
        _fail("observation_mismatch")
    canonical = _canonical(observed)
    result = SourceProvenanceComparison(
        schema=SOURCE_PROVENANCE_SCHEMA,
        receipt_sha256=expected_receipt_sha256,
        manifest_sha256=expected_manifest_sha256,
        source_tree_sha256=expected_source_tree_sha256,
        total_bytes=observation.total_bytes,
        files=tuple(dict(item) for item in observed["files"]),
        profile_pin_verified=True,
        signature_verification="not-performed",
        canonical_bytes=canonical,
        comparison_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    return result


__all__ = [
    "MAX_RECEIPT_BYTES",
    "SOURCE_PROVENANCE_SCHEMA",
    "SourceProvenanceComparison",
    "SourceProvenanceComparisonError",
    "compare_source_provenance",
]
