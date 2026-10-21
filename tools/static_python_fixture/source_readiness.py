"""Source-only readiness receipt for the static Python candidate.

This module joins the already detached archive, source-tree and staged-tree
evidence with the reviewed RSI source plan and a separately supplied Zig
inventory.  It never reads a path, acquires an archive, invokes a tool, or
authorizes a build.  The toolchain inventory is deliberately retained as an
unverified declaration until an independent toolchain audit supplies evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from .profile import CPYTHON_ARCHIVE, ZIG_ARCHIVE
from .source_provenance import (
    compare_source_provenance,
    validate_source_staging_consistency,
)
from .source_staging import StaticPythonSourceStaging
from .source_tree_observation import StaticPythonSourceTreeObservation
from .verified_inputs import StaticPythonVerifiedInputError

SOURCE_READINESS_SCHEMA = "lunar-static-python-source-readiness-receipt-v1"
TOOLCHAIN_INVENTORY_SCHEMA = "lunar-static-python-toolchain-inventory-v1"
_SOURCE_PLAN_SCHEMA = "lunar-static-python-rsi-launch-source-plan-v1"
_PROFILE = "rsi-marker-launch-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SOURCE_PLAN_BYTES = 16 * 1024
_MAX_TOOLCHAIN_INVENTORY_BYTES = 512 * 1024
_MAX_READINESS_BYTES = 512 * 1024
_MAX_TOOLCHAIN_FILES = 256
_MAX_TOOLCHAIN_FILE_BYTES = 4 * 1024 * 1024 * 1024
_MAX_PATH_BYTES = 4096
_ASSET_NAMES = frozenset({
    "launcher.c", "pipe.c", "profile.c", "getpath.c",
    "lunar_fixture_profile.h", "frozen_main.py",
})
_RECEIPT_CLAIMS = frozenset({
    "configure_performed", "compile_performed", "link_performed",
    "frozen_headers_generated", "runtime_execution_performed",
    "installation_accepted", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
})
_SOURCE_PLAN_CLAIMS = frozenset({
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
})
_SOURCE_PLAN_FIELDS = frozenset({
    "schema", "profile", "launch_policy", "initialization_profile", "source_inputs",
    "emitted_sources", "claims", "artifact_state", "startup_state",
})
_SOURCE_RECORD_FIELDS = frozenset({"path", "size", "sha256", "origin"})
_ASSET_RECORD_FIELDS = frozenset({"path", "size", "sha256"})
_TOOLCHAIN_FIELDS = frozenset({
    "schema", "profile", "archive", "url", "root", "version", "archive_size",
    "archive_sha256", "target", "llvm_version", "libc", "evidence_status", "files",
    "claims",
})
_TOOLCHAIN_FILE_FIELDS = frozenset({"path", "kind", "size", "mode", "sha256"})
_READINESS_FIELDS = frozenset({
    "schema", "status", "archive_receipt_sha256", "archive", "root", "version",
    "archive_size", "archive_sha256", "snapshot_sha256", "manifest_sha256",
    "source_tree_sha256", "staging_sha256", "patch_set_sha256", "policy_sha256",
    "projection_sha256", "declared_signature_verification", "observed_signature_verification",
    "source_plan_sha256", "source_assets", "expanded_frozen_main",
    "toolchain_inventory_sha256", "toolchain", "claims",
})


class StaticPythonSourceReadinessError(ValueError):
    """Fixed refusal without caller paths, source bytes or tool output."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_source_readiness_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonSourceReadinessError(reason)


def _sha(value: object, reason: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value in {"0" * 64, "f" * 64}:
        _fail(reason)
    return value


def _text(value: object, reason: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value:
        _fail(reason)
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail(reason)
    except UnicodeError:
        _fail(reason)
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        _fail(reason)
    return value


def _canonical(value: object, *, maximum: int) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise StaticPythonSourceReadinessError("canonical_invalid") from exc
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


def _constant(_: str) -> NoReturn:
    _fail("json_invalid")


def _load(raw: bytes, *, maximum: int) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        _fail("wire_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except StaticPythonSourceReadinessError:
        raise
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise StaticPythonSourceReadinessError("json_invalid") from exc
    if type(value) is not dict:
        _fail("json_invalid")
    if _canonical(value, maximum=maximum) != raw:
        _fail("noncanonical_json")
    return value


def _path(value: object, reason: str = "path_invalid", *, root: str | None = None) -> str:
    value = _text(value, reason, maximum=_MAX_PATH_BYTES)
    if "\\" in value or ":" in value:
        _fail(reason)
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail(reason)
    if root is not None and (value != root and not value.startswith(root + "/")):
        _fail(reason)
    return value


def _integer(value: object, reason: str, *, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _source_plan(raw: bytes, assets: dict[str, bytes], expected_sha256: str) -> tuple[
    dict[str, object], tuple[dict[str, object], ...], dict[str, object]
]:
    _sha(expected_sha256, "source_plan_pin_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("source_plan_pin_mismatch")
    # ``emit_rsi_launch_source_plan`` retains one terminal LF; the inner JSON
    # remains canonical and the exact bytes (including that LF) stay externally
    # pinned above.
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        _fail("source_plan_wire_invalid")
    plan = _load(raw[:-1], maximum=_MAX_SOURCE_PLAN_BYTES)
    if frozenset(plan) != _SOURCE_PLAN_FIELDS:
        _fail("source_plan_schema_invalid")
    if plan["schema"] != _SOURCE_PLAN_SCHEMA or plan["profile"] != _PROFILE:
        _fail("source_plan_schema_invalid")
    if plan["artifact_state"] != "pending-builder" or plan["startup_state"] != "not-executed":
        _fail("source_plan_state_invalid")
    claims = plan["claims"]
    if type(claims) is not dict or set(claims) != _SOURCE_PLAN_CLAIMS or any(
            type(value) is not bool or value for value in claims.values()):
        _fail("source_plan_claim_invalid")
    source_inputs = plan["source_inputs"]
    if type(source_inputs) is not list or len(source_inputs) != 11:
        _fail("source_plan_input_invalid")
    seen_inputs: set[str] = set()
    for item in source_inputs:
        if type(item) is not dict or frozenset(item) != _SOURCE_RECORD_FIELDS:
            _fail("source_plan_input_invalid")
        path = _path(item["path"])
        if path in seen_inputs:
            _fail("source_plan_input_invalid")
        seen_inputs.add(path)
        _integer(item["size"], "source_plan_size_invalid", maximum=128 * 1024)
        _sha(item["sha256"], "source_plan_digest_invalid")
        if item["origin"] not in {"original", "owned"}:
            _fail("source_plan_origin_invalid")
    emitted = plan["emitted_sources"]
    if type(emitted) is not list or len(emitted) != len(_ASSET_NAMES):
        _fail("source_plan_asset_invalid")
    records: list[dict[str, object]] = []
    seen_assets: set[str] = set()
    for item in emitted:
        if type(item) is not dict or frozenset(item) != _ASSET_RECORD_FIELDS:
            _fail("source_plan_asset_invalid")
        path = _path(item["path"])
        if not path.startswith("assets/") or path.removeprefix("assets/") in seen_assets:
            _fail("source_plan_asset_invalid")
        name = path.removeprefix("assets/")
        if name not in _ASSET_NAMES:
            _fail("source_plan_asset_invalid")
        seen_assets.add(name)
        size = _integer(item["size"], "source_plan_asset_size_invalid", maximum=16 * 1024)
        digest = _sha(item["sha256"], "source_plan_asset_digest_invalid")
        records.append({"path": path, "size": size, "sha256": digest})
    if seen_assets != _ASSET_NAMES:
        _fail("source_plan_asset_invalid")
    if type(assets) is not dict or set(assets) != _ASSET_NAMES or any(
            type(name) is not str or type(value) is not bytes for name, value in assets.items()):
        _fail("source_asset_input_invalid")
    for item in records:
        name = item["path"].removeprefix("assets/")
        value = assets[name]
        if len(value) != item["size"] or hashlib.sha256(value).hexdigest() != item["sha256"]:
            _fail("source_asset_digest_mismatch")
    return plan, tuple(sorted(records, key=lambda item: item["path"])), {
        "path": "assets/frozen_main.py",
        "size": next(item["size"] for item in records if item["path"] == "assets/frozen_main.py"),
        "sha256": next(item["sha256"] for item in records if item["path"] == "assets/frozen_main.py"),
    }


def _toolchain_inventory(raw: bytes, expected_sha256: str) -> dict[str, object]:
    _sha(expected_sha256, "toolchain_inventory_pin_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("toolchain_inventory_pin_mismatch")
    value = _load(raw, maximum=_MAX_TOOLCHAIN_INVENTORY_BYTES)
    if frozenset(value) != _TOOLCHAIN_FIELDS:
        _fail("toolchain_inventory_schema_invalid")
    expected = {
        "schema": TOOLCHAIN_INVENTORY_SCHEMA, "profile": "zig-0.16.0-linux-x86_64-musl",
        "archive": "zig", "url": ZIG_ARCHIVE["url"], "root": ZIG_ARCHIVE["root"],
        "version": "0.16.0", "archive_size": ZIG_ARCHIVE["size"],
        "archive_sha256": ZIG_ARCHIVE["sha256"], "target": "x86_64-linux-musl",
        "llvm_version": "21.1.0", "libc": ZIG_ARCHIVE["libc"],
        "evidence_status": "unverified",
    }
    for key, item in expected.items():
        if value[key] != item:
            _fail("toolchain_inventory_profile_mismatch")
    claims = value["claims"]
    if type(claims) is not dict or set(claims) != {
            "archive_bytes_verified", "file_bytes_verified", "signature_verified",
            "build_authorized", "production_admission",
    } or any(type(item) is not bool or item for item in claims.values()):
        _fail("toolchain_inventory_claim_invalid")
    files = value["files"]
    if type(files) is not list or not 1 <= len(files) <= _MAX_TOOLCHAIN_FILES:
        _fail("toolchain_inventory_files_invalid")
    paths: list[str] = []
    for item in files:
        if type(item) is not dict or frozenset(item) != _TOOLCHAIN_FILE_FIELDS:
            _fail("toolchain_inventory_file_invalid")
        path = _path(item["path"], "toolchain_inventory_path_invalid", root=value["root"])
        if item["kind"] != "file":
            _fail("toolchain_inventory_file_invalid")
        _integer(item["size"], "toolchain_inventory_size_invalid", maximum=_MAX_TOOLCHAIN_FILE_BYTES)
        _integer(item["mode"], "toolchain_inventory_mode_invalid", maximum=0o777)
        _sha(item["sha256"], "toolchain_inventory_digest_invalid")
        paths.append(path)
    if paths != sorted(set(paths)):
        _fail("toolchain_inventory_order_invalid")
    return value


@dataclass(frozen=True, slots=True)
class StaticPythonSourceReadinessReceipt:
    """Detached agreement evidence; never a build or runtime admission token."""

    canonical_json: bytes
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return json.loads(self.canonical_json)


def _validate_receipt_wire(raw: bytes, expected_sha256: str) -> dict[str, object]:
    _sha(expected_sha256, "receipt_pin_invalid")
    value = _load(raw, maximum=_MAX_READINESS_BYTES)
    if frozenset(value) != _READINESS_FIELDS:
        _fail("receipt_schema_invalid")
    if value["schema"] != SOURCE_READINESS_SCHEMA or value["status"] != "source-only":
        _fail("receipt_schema_invalid")
    for name in (
        "archive_receipt_sha256", "archive_sha256", "snapshot_sha256", "manifest_sha256",
        "source_tree_sha256", "staging_sha256", "patch_set_sha256", "policy_sha256",
        "projection_sha256", "source_plan_sha256", "toolchain_inventory_sha256",
    ):
        _sha(value[name], "receipt_digest_invalid")
    _text(value["archive"], "receipt_archive_invalid", maximum=16)
    _text(value["root"], "receipt_root_invalid")
    _text(value["version"], "receipt_version_invalid", maximum=32)
    _integer(value["archive_size"], "receipt_size_invalid", maximum=_MAX_TOOLCHAIN_FILE_BYTES * 16)
    if (value["archive"], value["root"], value["version"], value["archive_size"],
            value["archive_sha256"]) != (
                "cpython", CPYTHON_ARCHIVE["root"], "3.13.12", CPYTHON_ARCHIVE["size"],
                CPYTHON_ARCHIVE["sha256"],
            ):
        _fail("receipt_archive_profile_mismatch")
    if value["snapshot_sha256"] != value["archive_sha256"]:
        _fail("receipt_snapshot_mismatch")
    for name in ("declared_signature_verification", "observed_signature_verification"):
        if value[name] not in {"verified", "not-performed", "unavailable", "failed"}:
            _fail("receipt_signature_invalid")
    assets = value["source_assets"]
    if type(assets) is not list or len(assets) != len(_ASSET_NAMES):
        _fail("receipt_assets_invalid")
    paths = []
    for item in assets:
        if type(item) is not dict or frozenset(item) != _ASSET_RECORD_FIELDS:
            _fail("receipt_assets_invalid")
        _path(item["path"], "receipt_asset_path_invalid")
        _integer(item["size"], "receipt_asset_size_invalid", maximum=16 * 1024)
        _sha(item["sha256"], "receipt_asset_digest_invalid")
        paths.append(item["path"])
    if paths != sorted(set(paths)) or {path.removeprefix("assets/") for path in paths} != _ASSET_NAMES:
        _fail("receipt_assets_invalid")
    main = value["expanded_frozen_main"]
    if type(main) is not dict or frozenset(main) != _ASSET_RECORD_FIELDS or main["path"] != "assets/frozen_main.py":
        _fail("receipt_expanded_main_invalid")
    _integer(main["size"], "receipt_expanded_main_invalid", maximum=16 * 1024)
    _sha(main["sha256"], "receipt_expanded_main_invalid")
    if main != next(item for item in assets if item["path"] == "assets/frozen_main.py"):
        _fail("receipt_expanded_main_mismatch")
    toolchain = value["toolchain"]
    if type(toolchain) is not dict or frozenset(toolchain) != _TOOLCHAIN_FIELDS:
        _fail("receipt_toolchain_invalid")
    # Reuse the exact profile/file/claim checks on the retained projection.
    _toolchain_inventory(_canonical(toolchain, maximum=_MAX_TOOLCHAIN_INVENTORY_BYTES),
                         value["toolchain_inventory_sha256"])
    claims = value["claims"]
    if type(claims) is not dict or set(claims) != _RECEIPT_CLAIMS or any(
            type(item) is not bool or item for item in claims.values()):
        _fail("receipt_claim_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("receipt_digest_mismatch")
    return value


def build_source_readiness_receipt(
    archive_receipt_raw: bytes,
    observation: StaticPythonSourceTreeObservation,
    staging: StaticPythonSourceStaging,
    *,
    expected_receipt_sha256: str,
    expected_manifest_sha256: str,
    expected_source_tree_sha256: str,
    expected_staging_sha256: str,
    source_plan: bytes,
    expected_source_plan_sha256: str,
    source_assets: dict[str, bytes],
    toolchain_inventory: bytes,
    expected_toolchain_inventory_sha256: str,
) -> StaticPythonSourceReadinessReceipt:
    """Build one source-only receipt from independently pinned detached DTOs."""
    try:
        comparison = compare_source_provenance(
            archive_receipt_raw, observation,
            expected_receipt_sha256=expected_receipt_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_source_tree_sha256=expected_source_tree_sha256,
        )
        validate_source_staging_consistency(
            observation, staging,
            expected_staging_sha256=expected_staging_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_source_tree_sha256=expected_source_tree_sha256,
        )
        _plan, assets, expanded = _source_plan(
            source_plan, source_assets, expected_source_plan_sha256,
        )
        inventory = _toolchain_inventory(toolchain_inventory, expected_toolchain_inventory_sha256)
        staging_wire = staging.to_manifest()
        patch_set = staging_wire["patch_set_sha256"]
        policy = staging_wire["policy_sha256"]
        projection = staging_wire["projection_sha256"]
        for name, value in (("patch_set", patch_set), ("policy", policy), ("projection", projection)):
            _sha(value, name + "_digest_invalid")
        receipt = {
            "schema": SOURCE_READINESS_SCHEMA, "status": "source-only",
            "archive_receipt_sha256": comparison.receipt_sha256,
            "archive": observation.archive, "root": observation.root, "version": observation.version,
            # ``compare_source_provenance`` already checked this identity against
            # the canonical archive receipt size; retain that detached fact
            # without reparsing caller bytes.
            "archive_size": observation.source_identity.size,
            "archive_sha256": observation.archive_sha256, "snapshot_sha256": observation.snapshot_sha256,
            "manifest_sha256": expected_manifest_sha256,
            "source_tree_sha256": expected_source_tree_sha256, "staging_sha256": expected_staging_sha256,
            "patch_set_sha256": patch_set, "policy_sha256": policy, "projection_sha256": projection,
            "declared_signature_verification": comparison.declared_signature_verification,
            "observed_signature_verification": comparison.observed_signature_verification,
            "source_plan_sha256": expected_source_plan_sha256,
            "source_assets": list(assets), "expanded_frozen_main": expanded,
            "toolchain_inventory_sha256": expected_toolchain_inventory_sha256,
            "toolchain": inventory, "claims": dict.fromkeys(_RECEIPT_CLAIMS, False),
        }
        raw = _canonical(receipt, maximum=_MAX_READINESS_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        return StaticPythonSourceReadinessReceipt(raw, digest)
    except StaticPythonSourceReadinessError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, StaticPythonVerifiedInputError) as exc:
        raise StaticPythonSourceReadinessError("input_invalid") from exc


def validate_static_python_source_readiness_receipt(
    raw: bytes, *, expected_sha256: str,
) -> StaticPythonSourceReadinessReceipt:
    """Validate a retained receipt without upgrading any claim or reading paths."""
    _validate_receipt_wire(raw, expected_sha256)
    return StaticPythonSourceReadinessReceipt(raw, hashlib.sha256(raw).hexdigest())


__all__ = [
    "SOURCE_READINESS_SCHEMA", "TOOLCHAIN_INVENTORY_SCHEMA",
    "StaticPythonSourceReadinessError", "StaticPythonSourceReadinessReceipt",
    "build_source_readiness_receipt", "validate_static_python_source_readiness_receipt",
]
