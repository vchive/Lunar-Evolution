"""Detached provenance receipt for a candidate static-Python source tree.

The receipt records exactly which staged tree, source profile and fixed patch
policy a future builder is expected to consume.  It only compares caller
supplied canonical bytes: it never opens a path, runs a process, applies a
patch, builds an image, or grants runtime/admission authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from . import source_patches

CANDIDATE_BUILD_SOURCE_SCHEMA = "lunar-static-python-candidate-build-source-v1"
SOURCE_PROFILE_SCHEMA = "lunar-static-python-candidate-source-profile-v1"
MAX_CANDIDATE_BUILD_SOURCE_BYTES = 512 * 1024
MAX_PROFILE_BYTES = 64 * 1024
MAX_PATCH_SET_BYTES = 256 * 1024
MAX_STAGING_BYTES = 128 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_PATH = re.compile(r"[A-Za-z0-9_./+-]{1,4096}\Z")

_CLAIMS = frozenset({
    "source_execution_performed", "build_performed", "frozen_headers_generated",
    "runtime_execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
})
_PATCH_CLAIMS = frozenset({
    "source_execution_performed", "build_performed", "frozen_headers_generated",
    "execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
})

_STAGING_FIELDS = frozenset({
    "schema", "destination", "root", "root_directory", "archive", "archive_sha256",
    "snapshot_sha256", "manifest_sha256", "projection_sha256", "policy_sha256",
    "patch_set_sha256", "profile_pin_verified", "metadata_validation",
    "source_preimages_checked", "signature_verification", "tree_identity",
    "ancestor_identities", "entries", "extraction_performed", "fixed_patches_staged",
    "release_verified", "source_execution_performed", "build_performed",
    "frozen_headers_generated", "runtime_execution_performed", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
})
_STAGING_ENTRY_FIELDS = frozenset({
    "path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode",
    "device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns",
})
_PATCH_FIELDS = frozenset({
    "schema", "source_version", "source_commit", "provenance",
    "source_archive_verification", "source_signature_verification", "policy",
    "zipimport_policy", "abc_fallback_policy", "codec_lookup_policy", "patch_set_sha256",
    "files", "source_execution_performed", "build_performed", "frozen_headers_generated",
    "execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
})
_PATCH_FILE_FIELDS = frozenset({"path", "before_sha256", "before_size", "after_sha256", "after_size", "operations"})
_PATCH_OPERATION_FIELDS = frozenset({"label", "before_sha256", "before_size", "after_sha256", "after_size", "required_occurrences"})
_PROFILE_FIELDS = frozenset({
    "schema", "profile", "source_version", "source_commit", "source_archive_sha256",
    "source_tree_sha256", "patch_set_sha256", "claims",
})
_RECEIPT_FIELDS = frozenset({
    "schema", "status", "staged_tree_sha256", "staging_manifest_sha256",
    "source_archive_sha256", "source_tree_sha256", "source_profile_sha256",
    "source_profile", "patch_set_sha256", "patch_set", "claims",
})


class CandidateBuildSourceError(ValueError):
    """Fixed refusal code without caller-controlled paths or text."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,64}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_candidate_build_source_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object, reason: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _text(value: object, reason: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > maximum:
        _fail(reason)
    if any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value):
        _fail(reason)
    return value


def _integer(value: object, reason: str, *, maximum: int = 2**63 - 1, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _canonical(value: object, *, maximum: int) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise CandidateBuildSourceError("canonical_invalid") from exc
    if not 0 < len(raw) <= maximum:
        _fail("wire_budget_exceeded")
    return raw


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _load(raw: bytes, *, maximum: int, reason: str) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        _fail(reason + "_wire_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda _: _fail("json_invalid"))
    except _Refusal:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise CandidateBuildSourceError(reason + "_json_invalid") from exc
    if type(value) is not dict or _canonical(value, maximum=maximum) != raw:
        _fail(reason + "_canonical_invalid")
    return value


def _validate_claims(value: object, reason: str, fields: frozenset[str] = _CLAIMS) -> None:
    if type(value) is not dict or frozenset(value) != fields or any(type(item) is not bool or item for item in value.values()):
        _fail(reason)


def _validate_patch_files(files: object) -> list[dict[str, object]]:
    """Validate the exact bounded patch vector carried by policies/receipts."""
    if type(files) is not list or not files:
        _fail("patch_set_files_invalid")
    names: list[str] = []
    for item in files:
        if type(item) is not dict or frozenset(item) != _PATCH_FILE_FIELDS:
            _fail("patch_set_file_invalid")
        path = item["path"]
        if (type(path) is not str or _PATH.fullmatch(path) is None
                or path.startswith("/") or ".." in path.split("/")):
            _fail("patch_set_path_invalid")
        names.append(path)
        for name in ("before_sha256", "after_sha256"):
            _sha(item[name], "patch_set_digest_invalid")
        for name in ("before_size", "after_size"):
            _integer(item[name], "patch_set_size_invalid", maximum=2**31 - 1, minimum=1)
        operations = item["operations"]
        if type(operations) is not list or not operations:
            _fail("patch_set_operations_invalid")
        for operation in operations:
            if type(operation) is not dict or frozenset(operation) != _PATCH_OPERATION_FIELDS:
                _fail("patch_set_operation_invalid")
            _text(operation["label"], "patch_set_operation_invalid", maximum=256)
            for name in ("before_sha256", "after_sha256"):
                _sha(operation[name], "patch_set_operation_digest_invalid")
            for name in ("before_size", "after_size"):
                _integer(operation[name], "patch_set_operation_size_invalid",
                         maximum=2**31 - 1, minimum=1)
            _integer(operation["required_occurrences"], "patch_set_occurrence_invalid",
                     maximum=16, minimum=1)
    if names != sorted(set(names)):
        _fail("patch_set_files_order_invalid")
    return files


def _validate_fixed_patch_identity(policy: dict[str, object]) -> None:
    """Require the installation-owned complete policy, not a self-consistent substitute."""
    expected = source_patches.source_patch_manifest()
    if _canonical(policy, maximum=MAX_PATCH_SET_BYTES) != _canonical(
            expected, maximum=MAX_PATCH_SET_BYTES):
        _fail("patch_set_not_fixed")


def _validate_staging(raw: bytes, expected_sha256: str) -> tuple[dict[str, object], str]:
    _sha(expected_sha256, "staging_pin_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("staging_pin_mismatch")
    staging = _load(raw, maximum=MAX_STAGING_BYTES, reason="staging")
    if frozenset(staging) != _STAGING_FIELDS or staging["schema"] != "lunar-static-python-source-staging-v1":
        _fail("staging_schema_invalid")
    for name in ("archive_sha256", "snapshot_sha256", "manifest_sha256", "projection_sha256", "policy_sha256", "patch_set_sha256"):
        _sha(staging[name], "staging_digest_invalid")
    for name in ("destination", "root", "root_directory"):
        _text(staging[name], "staging_text_invalid")
    if (type(staging["destination"]) is not str
            or not staging["destination"].startswith("/")
            or "\\" in staging["destination"] or "\0" in staging["destination"]):
        _fail("staging_destination_invalid")
    destination_parts = staging["destination"][1:].split("/")
    if (not destination_parts or len(destination_parts) > 64
            or any(part in {"", ".", ".."} for part in destination_parts)):
        _fail("staging_destination_invalid")
    if (type(staging["archive"]) is not str or staging["archive"] != "cpython"
            or staging["root_directory"] != staging["destination"] + "/" + staging["root"]
            or staging["snapshot_sha256"] != staging["archive_sha256"]):
        _fail("staging_identity_invalid")
    if type(staging["entries"]) is not list or not 0 < len(staging["entries"]) <= 131_072:
        _fail("staging_entries_invalid")
    if (type(staging["profile_pin_verified"]) is not bool
            or (staging["profile_pin_verified"], staging["metadata_validation"])
            not in {(True, "validated"), (False, "skipped-inert-profile")}):
        _fail("staging_profile_state_invalid")
    if (type(staging["source_preimages_checked"]) is not bool
            or staging["source_preimages_checked"] is not True
            or staging["extraction_performed"] is not True
            or staging["fixed_patches_staged"] is not True
            or staging["release_verified"] is not False
            or staging["signature_verification"] != "not-performed"):
        _fail("staging_state_invalid")
    _validate_claims({name: staging[name] for name in _CLAIMS}, "staging_claim_invalid")
    tree_identity_fields = frozenset({"device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns"})
    tree_identity = staging["tree_identity"]
    if type(tree_identity) is not dict or frozenset(tree_identity) != tree_identity_fields:
        _fail("staging_tree_identity_invalid")
    for name in ("device", "inode", "raw_mode", "nlink", "size"):
        _integer(tree_identity[name], "staging_tree_identity_invalid")
    for name in ("mtime_ns", "ctime_ns"):
        if type(tree_identity[name]) is not int or not -(2**63) <= tree_identity[name] <= 2**63 - 1:
            _fail("staging_tree_identity_invalid")
    if tree_identity["raw_mode"] != 0o40700 or tree_identity["nlink"] < 1:
        _fail("staging_tree_identity_invalid")
    ancestors = staging["ancestor_identities"]
    if type(ancestors) is not list or len(ancestors) != len(destination_parts):
        _fail("staging_ancestor_identities_invalid")
    for ancestor in ancestors:
        if type(ancestor) is not dict or frozenset(ancestor) != frozenset({"device", "inode"}):
            _fail("staging_ancestor_identities_invalid")
        _integer(ancestor["device"], "staging_ancestor_identities_invalid")
        _integer(ancestor["inode"], "staging_ancestor_identities_invalid")
    entries = staging["entries"]
    paths: list[str] = []
    by_path: dict[str, dict[str, object]] = {}
    for item in entries:
        if type(item) is not dict or frozenset(item) != _STAGING_ENTRY_FIELDS:
            _fail("staging_entry_invalid")
        path = item["path"]
        if (type(path) is not str or _PATH.fullmatch(path) is None
                or len(path.encode("ascii")) > 1024 or "\\" in path or ":" in path
                or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/"))
                or len(path.split("/")) > 64
                or (path != staging["root"] and not path.startswith(staging["root"] + "/"))):
            _fail("staging_path_invalid")
        if type(item["kind"]) is not str or item["kind"] not in {"file", "directory"} or type(item["implicit"]) is not bool:
            _fail("staging_entry_invalid")
        for name in ("source_sha256", "staged_sha256"):
            if item[name] is not None:
                _sha(item[name], "staging_entry_digest_invalid")
        if item["kind"] == "file":
            if path == staging["root"]:
                _fail("staging_path_root_invalid")
            if item["implicit"] is not False:
                _fail("staging_entry_invalid")
            if item["source_sha256"] is None or item["staged_sha256"] is None:
                _fail("staging_entry_digest_invalid")
            if (type(item["archive_mode"]) is not int or not 0 <= item["archive_mode"] <= 0o777
                    or item["mode"] != 0o600 or item["nlink"] != 1):
                _fail("staging_entry_stat_invalid")
        elif item["source_sha256"] is not None or item["staged_sha256"] is not None:
            _fail("staging_entry_digest_invalid")
        elif item["kind"] == "directory":
            if item["mode"] != 0o700 or item["nlink"] < 1:
                _fail("staging_entry_stat_invalid")
            if item["implicit"] and item["archive_mode"] is not None:
                _fail("staging_entry_invalid")
            if not item["implicit"] and (type(item["archive_mode"]) is not int
                                          or not 0 <= item["archive_mode"] <= 0o777):
                _fail("staging_entry_invalid")
        else:
            _integer(item["archive_mode"], "staging_entry_stat_invalid", maximum=2**63 - 1)
        for name in ("device", "inode", "mode", "nlink", "size", "mtime_ns", "ctime_ns"):
            if name in {"mtime_ns", "ctime_ns"}:
                if type(item[name]) is not int or not -(2**63) <= item[name] <= 2**63 - 1:
                    _fail("staging_entry_stat_invalid")
            else:
                _integer(item[name], "staging_entry_stat_invalid", maximum=2**63 - 1)
        if item["nlink"] < 1:
            _fail("staging_entry_stat_invalid")
        paths.append(path)
        by_path[path] = item
    if paths != sorted(set(paths)):
        _fail("staging_entries_order_invalid")
    directory_paths = {path for path, item in by_path.items() if item["kind"] == "directory"}
    if staging["root"] not in directory_paths:
        _fail("staging_root_directory_missing")
    implicit_directories: set[str] = set()
    for path, item in by_path.items():
        if path == staging["root"]:
            if item["kind"] != "directory":
                _fail("staging_path_root_invalid")
            if item["implicit"]:
                implicit_directories.add(path)
            continue
        parent = path.rpartition("/")[0]
        while parent and parent != staging["root"]:
            if parent not in directory_paths:
                _fail("staging_directory_inventory_invalid")
            if by_path[parent]["implicit"]:
                implicit_directories.add(parent)
            parent = parent.rpartition("/")[0]
        if parent != staging["root"]:
            _fail("staging_path_root_invalid")
    if any(by_path[path]["implicit"] and path not in implicit_directories for path in directory_paths):
        _fail("staging_implicit_directory_invalid")
    _validate_claims({name: staging[name] for name in _CLAIMS}, "staging_claim_invalid")
    # The tree digest excludes host identity/timestamps, while retaining every
    # path and byte identity consumed by a candidate builder.
    projection = [{name: item[name] for name in ("path", "kind", "implicit", "source_sha256", "staged_sha256", "archive_mode", "size")} for item in entries]
    return staging, hashlib.sha256(_canonical(projection, maximum=MAX_STAGING_BYTES)).hexdigest()


def _validate_staged_source_binding(
    staging: dict[str, object],
    policy: dict[str, object],
    expected_source_tree_sha256: str,
) -> None:
    """Join every staged file to the fixed patch vector and rebuild source tree."""
    root = staging["root"]
    source_version = policy["source_version"]
    if root != "Python-" + source_version:
        _fail("staging_source_version_mismatch")
    patch_by_path = {
        root + "/" + item["path"]: item for item in policy["files"]
    }
    staged_files = {
        item["path"]: item for item in staging["entries"] if item["kind"] == "file"
    }
    if set(patch_by_path) - set(staged_files):
        _fail("staging_patch_inventory_mismatch")

    source_files = []
    for path, entry in staged_files.items():
        patch = patch_by_path.get(path)
        if patch is None:
            source_size = entry["size"]
            if entry["source_sha256"] != entry["staged_sha256"]:
                _fail("staging_unpatched_file_drift")
        else:
            source_size = patch["before_size"]
            if (entry["source_sha256"] != patch["before_sha256"]
                    or entry["staged_sha256"] != patch["after_sha256"]
                    or entry["size"] != patch["after_size"]):
                _fail("staging_patch_image_mismatch")
        source_files.append({
            "path": path, "mode": entry["archive_mode"],
            "size": source_size, "sha256": entry["source_sha256"],
        })
    source_tree = {
        "schema": "lunar-static-python-source-tree-v1",
        "archive": staging["archive"], "root": root,
        "version": source_version,
        "files": sorted(source_files, key=lambda item: item["path"]),
    }
    if hashlib.sha256(_canonical(source_tree, maximum=MAX_STAGING_BYTES)).hexdigest() != expected_source_tree_sha256:
        _fail("source_tree_staging_mismatch")


def _validate_patch_set(raw: bytes, expected_sha256: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    _sha(expected_sha256, "patch_set_pin_invalid")
    policy = _load(raw, maximum=MAX_PATCH_SET_BYTES, reason="patch_set")
    if frozenset(policy) != _PATCH_FIELDS or policy["schema"] != "lunar-static-python-source-preparation-v1":
        _fail("patch_set_schema_invalid")
    if policy["source_archive_verification"] not in {"not-performed", "verified", "unavailable", "failed"} or policy["source_signature_verification"] not in {"not-performed", "verified", "unavailable", "failed"}:
        _fail("patch_set_verification_invalid")
    for name in ("source_version", "source_commit", "provenance", "policy", "zipimport_policy", "abc_fallback_policy", "codec_lookup_policy"):
        _text(policy[name], "patch_set_text_invalid")
    _validate_claims({name: policy[name] for name in _PATCH_CLAIMS}, "patch_set_claim_invalid", fields=_PATCH_CLAIMS)
    files = _validate_patch_files(policy["files"])
    files_raw = _canonical(files, maximum=MAX_PATCH_SET_BYTES)
    if hashlib.sha256(files_raw).hexdigest() != policy["patch_set_sha256"] or policy["patch_set_sha256"] != expected_sha256:
        _fail("patch_set_digest_mismatch")
    _validate_fixed_patch_identity(policy)
    return policy, files


def _validate_profile(raw: bytes, expected_sha256: str, expected_source_tree_sha256: str, patch_set_sha256: str) -> dict[str, object]:
    _sha(expected_sha256, "source_profile_pin_invalid")
    _sha(expected_source_tree_sha256, "source_tree_pin_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("source_profile_pin_mismatch")
    profile = _load(raw, maximum=MAX_PROFILE_BYTES, reason="source_profile")
    if frozenset(profile) != _PROFILE_FIELDS or profile["schema"] != SOURCE_PROFILE_SCHEMA:
        _fail("source_profile_schema_invalid")
    for name in ("profile", "source_version", "source_commit"):
        _text(profile[name], "source_profile_text_invalid")
    for name in ("source_archive_sha256", "source_tree_sha256", "patch_set_sha256"):
        _sha(profile[name], "source_profile_digest_invalid")
    if profile["source_tree_sha256"] != expected_source_tree_sha256 or profile["patch_set_sha256"] != patch_set_sha256:
        _fail("source_profile_binding_mismatch")
    _validate_claims(profile["claims"], "source_profile_claim_invalid")
    return profile


@dataclass(frozen=True, slots=True)
class CandidateBuildSourceReceipt:
    """Detached source/build-input agreement; never an execution token."""

    canonical_json: bytes
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.canonical_json)

    def to_json(self) -> bytes:
        return self.canonical_json


def build_candidate_build_source_receipt(
    staging_manifest: bytes,
    *,
    expected_staging_manifest_sha256: str,
    expected_staged_tree_sha256: str,
    patch_set: bytes,
    expected_patch_set_sha256: str,
    source_profile: bytes,
    expected_source_profile_sha256: str,
    expected_source_tree_sha256: str,
) -> CandidateBuildSourceReceipt:
    """Join independently pinned source/profile, exact patch and staged-tree wires."""
    try:
        _sha(expected_staged_tree_sha256, "staged_tree_pin_invalid")
        staging, staged_tree_sha256 = _validate_staging(staging_manifest, expected_staging_manifest_sha256)
        if staged_tree_sha256 != expected_staged_tree_sha256:
            _fail("staged_tree_pin_mismatch")
        policy, files = _validate_patch_set(patch_set, expected_patch_set_sha256)
        if staging["patch_set_sha256"] != policy["patch_set_sha256"]:
            _fail("staging_patch_set_mismatch")
        expected_policy_sha256 = hashlib.sha256(
            _canonical(policy, maximum=MAX_PATCH_SET_BYTES)
        ).hexdigest()
        if staging["policy_sha256"] != expected_policy_sha256:
            _fail("staging_policy_mismatch")
        _validate_staged_source_binding(staging, policy, expected_source_tree_sha256)
        profile = _validate_profile(source_profile, expected_source_profile_sha256, expected_source_tree_sha256, policy["patch_set_sha256"])
        if profile["source_archive_sha256"] != staging["archive_sha256"]:
            _fail("archive_binding_mismatch")
        if profile["source_version"] != policy["source_version"] or profile["source_commit"] != policy["source_commit"]:
            _fail("source_profile_patch_mismatch")
        record = {
            "schema": CANDIDATE_BUILD_SOURCE_SCHEMA, "status": "source-only",
            "staged_tree_sha256": expected_staged_tree_sha256,
            "staging_manifest_sha256": expected_staging_manifest_sha256,
            "source_archive_sha256": profile["source_archive_sha256"],
            "source_tree_sha256": expected_source_tree_sha256,
            "source_profile_sha256": expected_source_profile_sha256,
            "source_profile": profile,
            "patch_set_sha256": policy["patch_set_sha256"],
            "patch_set": {"schema": policy["schema"], "source_version": policy["source_version"], "source_commit": policy["source_commit"], "files": files},
            "claims": dict.fromkeys(_CLAIMS, False),
        }
        raw = _canonical(record, maximum=MAX_CANDIDATE_BUILD_SOURCE_BYTES)
        return CandidateBuildSourceReceipt(raw, hashlib.sha256(raw).hexdigest())
    except _Refusal as exc:
        raise CandidateBuildSourceError(exc.reason) from None
    except CandidateBuildSourceError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise CandidateBuildSourceError("input_invalid") from exc


def validate_candidate_build_source_receipt(raw: bytes, *, expected_sha256: str) -> CandidateBuildSourceReceipt:
    """Validate a retained receipt without filesystem/build/runtime effects."""
    try:
        _sha(expected_sha256, "receipt_pin_invalid")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            _fail("receipt_pin_mismatch")
        value = _load(raw, maximum=MAX_CANDIDATE_BUILD_SOURCE_BYTES, reason="receipt")
        if frozenset(value) != _RECEIPT_FIELDS or value["schema"] != CANDIDATE_BUILD_SOURCE_SCHEMA or value["status"] != "source-only":
            _fail("receipt_schema_invalid")
        for name in ("staged_tree_sha256", "staging_manifest_sha256", "source_archive_sha256", "source_tree_sha256", "source_profile_sha256", "patch_set_sha256"):
            _sha(value[name], "receipt_digest_invalid")
        _validate_claims(value["claims"], "receipt_claim_invalid")
        profile_raw = _canonical(value["source_profile"], maximum=MAX_PROFILE_BYTES)
        profile = _validate_profile(profile_raw, value["source_profile_sha256"], value["source_tree_sha256"], value["patch_set_sha256"])
        if profile["source_archive_sha256"] != value["source_archive_sha256"]:
            _fail("receipt_archive_binding_mismatch")
        patch = value["patch_set"]
        if type(patch) is not dict or frozenset(patch) != frozenset({"schema", "source_version", "source_commit", "files"}):
            _fail("receipt_patch_set_invalid")
        _text(patch["source_version"], "receipt_patch_set_invalid")
        _text(patch["source_commit"], "receipt_patch_set_invalid")
        if (patch["source_version"] != profile["source_version"]
                or patch["source_commit"] != profile["source_commit"]):
            _fail("receipt_patch_profile_mismatch")
        files = _validate_patch_files(patch["files"])
        files_raw = _canonical(patch["files"], maximum=MAX_PATCH_SET_BYTES)
        _sha(value["patch_set_sha256"], "receipt_patch_set_invalid")
        if hashlib.sha256(files_raw).hexdigest() != value["patch_set_sha256"]:
            _fail("receipt_patch_set_mismatch")
        if patch["schema"] != "lunar-static-python-source-preparation-v1" or not isinstance(patch["files"], list):
            _fail("receipt_patch_set_invalid")
        if patch["source_version"] != profile["source_version"] or patch["source_commit"] != profile["source_commit"]:
            _fail("receipt_patch_profile_mismatch")
        expected_policy = source_patches.source_patch_manifest()
        if (patch["source_version"] != expected_policy["source_version"]
                or patch["source_commit"] != expected_policy["source_commit"]
                or _canonical(files, maximum=MAX_PATCH_SET_BYTES)
                != _canonical(expected_policy["files"], maximum=MAX_PATCH_SET_BYTES)
                or value["patch_set_sha256"] != expected_policy["patch_set_sha256"]):
            _fail("receipt_patch_set_not_fixed")
        return CandidateBuildSourceReceipt(raw, expected_sha256)
    except _Refusal as exc:
        raise CandidateBuildSourceError(exc.reason) from None
    except CandidateBuildSourceError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise CandidateBuildSourceError("receipt_invalid") from exc


# Short aliases used by callers that refer to the artifact as a source receipt.
build_candidate_source_receipt = build_candidate_build_source_receipt
validate_candidate_source_receipt = validate_candidate_build_source_receipt

__all__ = [
    "CANDIDATE_BUILD_SOURCE_SCHEMA",
    "MAX_CANDIDATE_BUILD_SOURCE_BYTES",
    "SOURCE_PROFILE_SCHEMA",
    "CandidateBuildSourceError",
    "CandidateBuildSourceReceipt",
    "build_candidate_build_source_receipt",
    "build_candidate_source_receipt",
    "validate_candidate_build_source_receipt",
    "validate_candidate_source_receipt",
]
