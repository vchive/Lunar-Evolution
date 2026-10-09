"""Pure validation of fixed archive and extraction *claims* for Feature189.

These inputs are detached metadata, not archive bytes or filesystem observations.
The validator does not download, verify a signature, read files, inspect tar
headers, extract, build or execute anything. In particular, a receipt that says
``verified`` only records its caller's signature-verification declaration.
Matching extraction member hashes does not establish that those bytes exist.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from .profile import CPYTHON_ARCHIVE, TARGET, ZIG_ARCHIVE
from .source_patches import SOURCE_VERSION, source_patch_manifest

ARCHIVE_RECEIPT_SCHEMA = "lunar-static-python-archive-receipt-v1"
EXTRACTION_MANIFEST_SCHEMA = "lunar-static-python-extraction-manifest-v1"
MAX_ARCHIVE_RECEIPT_BYTES = 16 * 1024
MAX_EXTRACTION_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_EXTRACTION_MEMBERS = 65_536
MAX_EXTRACTION_MEMBER_BYTES = 256 * 1024 * 1024
MAX_EXTRACTION_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTION_PATH_BYTES = 1024
MAX_EXTRACTION_PATH_SEGMENTS = 64
MAX_EXTRACTION_TOTAL_PATH_BYTES = 16 * 1024 * 1024

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_FIELDS = frozenset({
    "schema", "archive", "url", "size", "sha256", "root", "version", "identity",
    "signature_verification",
})
_MANIFEST_FIELDS = frozenset({"schema", "archive", "root", "archive_sha256", "members"})
_MEMBER_FIELDS = frozenset({"path", "kind", "size", "mode", "sha256"})
_SIGNATURE_STATUSES = frozenset({"verified", "not-performed", "unavailable", "failed"})


class StaticPythonVerifiedInputError(ValueError):
    """A fixed refusal code, without caller-controlled metadata in the error."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_verified_input_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonVerifiedInputError(reason)


@dataclass(frozen=True, slots=True)
class _ArchiveProfile:
    archive: str
    url: str
    size: int
    sha256: str
    root: str
    version: str
    identity: tuple[tuple[str, str], ...]


# Snapshot the installation-owned pins into immutable values. Caller mutation
# of metadata, or a returned DTO, cannot rewrite a profile or later result.
_CPYTHON = _ArchiveProfile(
    archive="cpython", url=CPYTHON_ARCHIVE["url"], size=CPYTHON_ARCHIVE["size"],
    sha256=CPYTHON_ARCHIVE["sha256"], root=CPYTHON_ARCHIVE["root"], version=SOURCE_VERSION,
    identity=(("commit", CPYTHON_ARCHIVE["commit"]), ("tag", CPYTHON_ARCHIVE["tag"])),
)
_ZIG = _ArchiveProfile(
    archive="zig", url=ZIG_ARCHIVE["url"], size=ZIG_ARCHIVE["size"],
    sha256=ZIG_ARCHIVE["sha256"], root=ZIG_ARCHIVE["root"], version="0.16.0",
    identity=tuple(sorted({
        "target": TARGET, "llvm_version": ZIG_ARCHIVE["llvm_version"],
        "libc": ZIG_ARCHIVE["libc"],
    }.items())),
)


@dataclass(frozen=True, slots=True)
class StaticPythonArchiveReceipt:
    """Immutable canonical receipt metadata; no verification was performed here."""

    schema: str
    archive: str
    url: str
    size: int
    sha256: str
    root: str
    version: str
    identity: tuple[tuple[str, str], ...]
    signature_verification: str
    canonical_json: bytes
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class StaticPythonArchiveMember:
    """One detached regular-file or directory metadata claim."""

    path: str
    kind: str
    size: int
    mode: int
    sha256: str | None


@dataclass(frozen=True, slots=True)
class StaticPythonExtractionManifest:
    """Canonical member inventory, independent of mutable caller containers."""

    schema: str
    archive: str
    root: str
    archive_sha256: str
    members: tuple[StaticPythonArchiveMember, ...]
    total_bytes: int
    source_preimages_checked: bool
    canonical_json: bytes
    manifest_sha256: str


def _object(value: object, fields: frozenset[str], reason: str) -> dict[str, Any]:
    # Check all keys before hashing, comparing, sorting, serializing or looking
    # up anything supplied by a caller. Mapping subclasses can run callbacks.
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str or len(key) > 64 for key in value)
            or set(value) != fields):
        _fail(reason)
    return value


def _profile(archive: object) -> _ArchiveProfile:
    if type(archive) is not str:
        _fail("archive_invalid")
    if archive == "cpython":
        return _CPYTHON
    if archive == "zig":
        return _ZIG
    _fail("archive_invalid")


def _text(value: object, reason: str, *, limit: int = 4096) -> str:
    if type(value) is not str or not value or len(value) > limit:
        _fail(reason)
    try:
        if len(value.encode("utf-8")) > limit:
            _fail(reason)
    except UnicodeError as exc:
        raise StaticPythonVerifiedInputError(reason) from exc
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        _fail(reason)
    return value


def _sha(value: object, reason: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(reason)
    return value


def _expected_digest(value: object) -> str:
    digest = _sha(value, "expected_digest_invalid")
    if digest == "f" * 64:
        _fail("expected_digest_invalid")
    return digest


def _canonical(value: object, *, limit: int) -> bytes:
    # Callers reach this only after every child is an exact, bounded builtin.
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > limit:
        _fail("canonical_budget_exceeded")
    return raw


def _receipt_json(raw: object) -> dict[str, Any]:
    if type(raw) is not bytes:
        _fail("receipt_bytes_invalid")
    if not 0 < len(raw) <= MAX_ARCHIVE_RECEIPT_BYTES:
        _fail("receipt_budget_exceeded")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: _fail("json_invalid"))
    except StaticPythonVerifiedInputError:
        raise
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise StaticPythonVerifiedInputError("json_invalid") from exc
    return _object(value, _RECEIPT_FIELDS, "receipt_shape_invalid")


def validate_static_python_archive_receipt(
    raw: bytes, *, expected_sha256: str,
) -> StaticPythonArchiveReceipt:
    """Validate canonical fixed-pin metadata; do not verify an actual archive.

    All four signature result spellings are declarations. Even ``verified`` is
    not cryptographic evidence supplied by this function, and ``failed`` cannot
    be turned into builder or production permission by validating its shape.
    """
    value = _receipt_json(raw)
    profile = _profile(value["archive"])
    if _text(value["schema"], "receipt_schema_invalid") != ARCHIVE_RECEIPT_SCHEMA:
        _fail("receipt_schema_invalid")
    for name in ("url", "root", "version"):
        if _text(value[name], "archive_pin_drift") != getattr(profile, name):
            _fail("archive_pin_drift")
    if type(value["size"]) is not int or value["size"] != profile.size:
        _fail("archive_pin_drift")
    if _sha(value["sha256"], "archive_pin_drift") != profile.sha256:
        _fail("archive_pin_drift")
    identity = _object(value["identity"], frozenset(key for key, _ in profile.identity),
                       "archive_identity_drift")
    for key, expected in profile.identity:
        if _text(identity[key], "archive_identity_drift") != expected:
            _fail("archive_identity_drift")
    signature = _text(value["signature_verification"], "signature_status_invalid", limit=32)
    if signature not in _SIGNATURE_STATUSES:
        _fail("signature_status_invalid")
    expected = _expected_digest(expected_sha256)
    canonical = _canonical(value, limit=MAX_ARCHIVE_RECEIPT_BYTES)
    if raw != canonical:
        _fail("receipt_noncanonical_json")
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected:
        _fail("receipt_digest_drift")
    return StaticPythonArchiveReceipt(
        schema=ARCHIVE_RECEIPT_SCHEMA, archive=profile.archive, url=profile.url,
        size=profile.size, sha256=profile.sha256, root=profile.root, version=profile.version,
        identity=profile.identity, signature_verification=signature, canonical_json=canonical,
        receipt_sha256=digest,
    )


def _path(value: object, root: str) -> str:
    path = _text(value, "member_path_invalid", limit=MAX_EXTRACTION_PATH_BYTES)
    # These are POSIX archive member names, not filesystem paths to normalize.
    # Refuse spellings which would need normalization rather than changing them.
    parts = path.split("/")
    if (len(parts) > MAX_EXTRACTION_PATH_SEGMENTS or parts[0] != root
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in path or ":" in path):
        _fail("member_path_invalid")
    return path


def _member(value: object, root: str) -> dict[str, Any]:
    item = _object(value, _MEMBER_FIELDS, "member_shape_invalid")
    path = _path(item["path"], root)
    kind = item["kind"]
    if type(kind) is not str or len(kind) > 9 or kind not in {"file", "directory"}:
        _fail("member_kind_invalid")
    size = item["size"]
    if type(size) is not int or not 0 <= size <= MAX_EXTRACTION_MEMBER_BYTES:
        _fail("member_size_invalid")
    mode = item["mode"]
    if type(mode) is not int or not 0 <= mode <= 0o777:
        _fail("member_mode_invalid")
    sha = item["sha256"]
    if kind == "directory":
        if size != 0 or sha is not None:
            _fail("directory_metadata_invalid")
    else:
        sha = _sha(sha, "member_digest_invalid")
    return {"path": path, "kind": kind, "size": size, "mode": mode, "sha256": sha}


def _check_source_preimages(members: dict[str, dict[str, Any]], profile: _ArchiveProfile) -> None:
    if profile.archive != "cpython":
        _fail("source_preimages_archive_invalid")
    # This only compares already validated member claims against fixed reviewed
    # preimage metadata. It neither reads nor authenticates source bytes.
    for source in source_patch_manifest()["files"]:
        member = members.get(profile.root + "/" + source["path"])
        if (member is None or member["kind"] != "file"
                or member["size"] != source["before_size"]
                or member["sha256"] != source["before_sha256"]):
            _fail("source_preimage_drift")


def validate_static_python_extraction_manifest(
    value: object, *, expected_sha256: str, require_source_preimages: bool = False,
) -> StaticPythonExtractionManifest:
    """Canonicalize a bounded inventory of claimed regular files/directories.

    Member paths include the pinned archive root. The root must be explicitly
    present as a directory; other parent directories may be implicit. No link,
    device, FIFO, sparse member or extraction behavior is represented by this
    schema. Arbitrary input order is canonicalized to unique ascending paths.
    """
    if type(require_source_preimages) is not bool:
        _fail("source_preimages_flag_invalid")
    value = _object(value, _MANIFEST_FIELDS, "manifest_shape_invalid")
    profile = _profile(value["archive"])
    if _text(value["schema"], "manifest_schema_invalid") != EXTRACTION_MANIFEST_SCHEMA:
        _fail("manifest_schema_invalid")
    if (_text(value["root"], "archive_pin_drift") != profile.root
            or _sha(value["archive_sha256"], "archive_pin_drift") != profile.sha256):
        _fail("archive_pin_drift")
    vector = value["members"]
    if type(vector) is not list or not 1 <= len(vector) <= MAX_EXTRACTION_MEMBERS:
        _fail("member_budget_exceeded")
    members: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    total_path_bytes = 0
    for raw in vector:
        item = _member(raw, profile.root)
        path = item["path"]
        if path in members:
            _fail("member_duplicate_path")
        total_bytes += item["size"]
        total_path_bytes += len(path.encode("utf-8"))
        if total_bytes > MAX_EXTRACTION_TOTAL_BYTES:
            _fail("total_byte_budget_exceeded")
        if total_path_bytes > MAX_EXTRACTION_TOTAL_PATH_BYTES:
            _fail("total_path_budget_exceeded")
        members[path] = item
    root_member = members.get(profile.root)
    if root_member is None or root_member["kind"] != "directory":
        _fail("root_directory_missing")
    for path in members:
        parent = path.rpartition("/")[0]
        while parent:
            ancestor = members.get(parent)
            if ancestor is not None and ancestor["kind"] != "directory":
                _fail("file_directory_collision")
            parent = parent.rpartition("/")[0]
    if require_source_preimages:
        _check_source_preimages(members, profile)
    expected = _expected_digest(expected_sha256)
    ordered = [members[path] for path in sorted(members)]
    canonical = _canonical({
        "schema": EXTRACTION_MANIFEST_SCHEMA, "archive": profile.archive,
        "root": profile.root, "archive_sha256": profile.sha256, "members": ordered,
    }, limit=MAX_EXTRACTION_MANIFEST_BYTES)
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != expected:
        _fail("manifest_digest_drift")
    return StaticPythonExtractionManifest(
        schema=EXTRACTION_MANIFEST_SCHEMA, archive=profile.archive, root=profile.root,
        archive_sha256=profile.sha256,
        members=tuple(StaticPythonArchiveMember(**member) for member in ordered),
        total_bytes=total_bytes, source_preimages_checked=require_source_preimages,
        canonical_json=canonical, manifest_sha256=digest,
    )


__all__ = [
    "ARCHIVE_RECEIPT_SCHEMA",
    "EXTRACTION_MANIFEST_SCHEMA",
    "MAX_ARCHIVE_RECEIPT_BYTES",
    "MAX_EXTRACTION_MANIFEST_BYTES",
    "MAX_EXTRACTION_MEMBERS",
    "MAX_EXTRACTION_MEMBER_BYTES",
    "MAX_EXTRACTION_PATH_BYTES",
    "MAX_EXTRACTION_PATH_SEGMENTS",
    "MAX_EXTRACTION_TOTAL_BYTES",
    "MAX_EXTRACTION_TOTAL_PATH_BYTES",
    "StaticPythonArchiveMember",
    "StaticPythonArchiveReceipt",
    "StaticPythonExtractionManifest",
    "StaticPythonVerifiedInputError",
    "validate_static_python_archive_receipt",
    "validate_static_python_extraction_manifest",
]
