"""Canonical registration seal and read-only launch preflight.

The registration contract is deliberately separate from the observation auditor:
a manifest and seal are prepared before a registration commit, then this module
checks the committed bytes and checkout state without invoking any provider,
campaign, candidate, evaluator, or generated source.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .acceptance_observer import DEFAULT_ACCEPTANCE_BUDGETS
from .candidate_workspace_plan import CandidateWorkspaceError
from .holdout_audit import MAX_DURATION_MS, MAX_HOLDOUTS

SCHEMA_VERSION = "1"
REGISTRATION_SCOPE = "acceptance_registration"
SEAL_SCOPE = "acceptance_registration_seal"
PREFLIGHT_SCOPE = "acceptance_registration_preflight"
MAX_REGISTRATION_BYTES = 128 * 1024
MAX_PRODUCT_FILES = 512
MAX_PRODUCT_FILE_BYTES = 8 * 1024 * 1024
MAX_PATH_BYTES = 1024
MAX_FROZEN_IDENTITIES = 256
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_REF = re.compile(r"^origin/[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_PRIVATE = re.compile(r"(?i)(prompt|response|credential|secret|token|endpoint|url|exception|traceback)")
_BUDGET_KEYS = frozenset(DEFAULT_ACCEPTANCE_BUDGETS)
_REGISTRATION_KEYS = frozenset({
    "schema_version", "scope", "registration_id", "campaign_id", "attempt_id",
    "product_commit", "product_files", "task_material", "input_material", "evaluator_material",
    "evaluator_profile_material", "campaign_root", "task_sha256", "input_sha256",
    "evaluator_sha256", "evaluator_profile_sha256", "provider", "model", "runtime",
    "api_mode", "entrypoint", "budgets", "islands", "population_size", "offspring_count",
    "rounds", "candidate_tool_steps", "holdout_pins", "frozen_identities",
    "frozen_identities_sha256",
})
_MATERIAL_KEYS = frozenset({"path", "size", "sha256"})
_HOLDOUT_KEYS = frozenset({"holdout_id", "ordinal", "input", "expected", "max_duration_ms"})
_FROZEN_KEYS = frozenset({"registration_id", "campaign_id", "campaign_root"})
_SEAL_KEYS = frozenset({
    "schema_version", "scope", "registration_sha256", "registration_id", "campaign_id",
    "attempt_id", "product_commit", "campaign_root", "seal_sha256",
})


class AcceptanceRegistrationError(ValueError):
    """A fixed public code for an unsafe registration or preflight observation."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]+", code) else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceRegistrationError(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("registration_json_invalid")
    if len(result) > MAX_REGISTRATION_BYTES:
        _fail("registration_too_large")
    return result


def _parse_json(value: str) -> dict[str, Any]:
    try:
        if len(value.encode("utf-8")) > MAX_REGISTRATION_BYTES:
            _fail("registration_too_large")
    except UnicodeError:
        _fail("registration_json_invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                _fail("registration_duplicate_key")
            result[key] = item
        return result

    try:
        loaded = json.loads(value, object_pairs_hook=pairs)
    except AcceptanceRegistrationError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("registration_json_invalid")
    if not isinstance(loaded, dict):
        _fail("registration_schema_invalid")
    if _canonical(loaded).decode("utf-8") != value:
        _fail("registration_noncanonical")
    return loaded


def _text(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    return _text(value, _SHA, code)


def _relative(value: object, code: str) -> str:
    if type(value) is not str or not value:
        _fail(code)
    try:
        if len(value.encode("utf-8")) > MAX_PATH_BYTES:
            _fail(code)
    except UnicodeError:
        _fail(code)
    if "\\" in value or ":" in value or "\x00" in value or value.startswith("/"):
        _fail(code)
    parts = value.split("/")
    if any(not part or part in {".", "..", ".git"} or any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts):
        _fail(code)
    return value


def _private(value: object, depth: int = 0) -> None:
    if depth > 4:
        _fail("registration_schema_invalid")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key not in _BUDGET_KEYS and _PRIVATE.search(key):
                _fail("private_registration_field")
            _private(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _private(item, depth + 1)


def _material(value: object, code: str = "material_invalid") -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _MATERIAL_KEYS:
        _fail(code)
    path = _relative(value.get("path"), f"{code}_path")
    size = value.get("size")
    if type(size) is not int or not 0 <= size <= MAX_PRODUCT_FILE_BYTES:
        _fail(f"{code}_size")
    return {"path": path, "size": size, "sha256": _sha(value.get("sha256"), f"{code}_digest")}


def _files(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PRODUCT_FILES:
        _fail("product_files_invalid")
    parsed: list[dict[str, Any]] = []
    previous = None
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _MATERIAL_KEYS:
            _fail("product_files_invalid")
        path = _relative(item.get("path"), "product_path_invalid")
        if previous is not None and path <= previous:
            _fail("product_files_order_invalid")
        previous = path
        size = item.get("size")
        if type(size) is not int or not 0 <= size <= MAX_PRODUCT_FILE_BYTES:
            _fail("product_file_size_invalid")
        parsed.append({"path": path, "size": size, "sha256": _sha(item.get("sha256"), "product_file_digest_invalid")})
    return parsed


def _holdouts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != MAX_HOLDOUTS:
        _fail("holdout_pins_invalid")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != _HOLDOUT_KEYS:
            _fail("holdout_pins_invalid")
        holdout_id = _text(item.get("holdout_id"), _ID, "holdout_id_invalid")
        if holdout_id in seen or type(item.get("ordinal")) is not int or item.get("ordinal") != index:
            _fail("holdout_pins_invalid")
        seen.add(holdout_id)
        duration = item.get("max_duration_ms")
        if type(duration) is not int or not 1 <= duration <= MAX_DURATION_MS:
            _fail("holdout_duration_invalid")
        parsed.append({
            "holdout_id": holdout_id, "ordinal": index,
            "input": _material(item.get("input"), "holdout_input_invalid"),
            "expected": _material(item.get("expected"), "holdout_expected_invalid"),
            "max_duration_ms": duration,
        })
    return parsed


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REGISTRATION_KEYS:
        _fail("registration_schema_invalid")
    _private(value)
    if value.get("schema_version") != SCHEMA_VERSION or value.get("scope") != REGISTRATION_SCOPE:
        _fail("registration_schema_invalid")
    for key in ("registration_id", "campaign_id", "provider", "model", "runtime", "api_mode"):
        _text(value.get(key), _ID, f"invalid_{key}")
    _text(value.get("attempt_id"), _ID, "invalid_attempt_id")
    if value["attempt_id"] != "attempt-001":
        _fail("invalid_attempt_id")
    _text(value.get("product_commit"), _COMMIT, "invalid_product_commit")
    _text(value.get("campaign_root"), _ROOT, "invalid_campaign_root")
    for key in ("task_sha256", "input_sha256", "evaluator_sha256", "evaluator_profile_sha256"):
        _sha(value.get(key), f"invalid_{key}")
    _relative(value.get("entrypoint"), "invalid_entrypoint")
    budgets = value.get("budgets")
    if not isinstance(budgets, Mapping) or set(budgets) != _BUDGET_KEYS:
        _fail("invalid_budgets")
    if any(type(budgets[key]) is not int for key in _BUDGET_KEYS) or dict(budgets) != dict(DEFAULT_ACCEPTANCE_BUDGETS):
        _fail("budgets_do_not_match_plan")
    limits = {
        "islands": (1, 1), "population_size": (1, 1), "offspring_count": (1, 1),
        "rounds": (1, 1), "candidate_tool_steps": (12, 12),
    }
    for key, (minimum, maximum) in limits.items():
        item = value.get(key)
        if type(item) is not int or not minimum <= item <= maximum:
            _fail(f"invalid_{key}")
    materials = {
        key: _material(value[key], key)
        for key in ("task_material", "input_material", "evaluator_material", "evaluator_profile_material")
    }
    material_digests = {
        "task_material": value["task_sha256"],
        "input_material": value["input_sha256"],
        "evaluator_material": value["evaluator_sha256"],
        "evaluator_profile_material": value["evaluator_profile_sha256"],
    }
    if any(materials[key]["sha256"] != digest for key, digest in material_digests.items()):
        _fail("material_digest_mismatch")
    product_files = _files(value["product_files"])
    if any(Path(item["path"]).name in {"registration.json", "registration-seal.json"} for item in product_files):
        _fail("product_path_reserved")
    all_paths = [item["path"] for item in materials.values()] + [item["path"] for item in product_files]
    for item in _holdouts(value["holdout_pins"]):
        all_paths.extend((item["input"]["path"], item["expected"]["path"]))
    if len(all_paths) != len(set(all_paths)):
        _fail("material_path_duplicate")
    frozen = value.get("frozen_identities")
    if not isinstance(frozen, Mapping) or set(frozen) != _FROZEN_KEYS:
        _fail("frozen_identities_invalid")
    frozen_out: dict[str, list[str]] = {}
    for key in sorted(_FROZEN_KEYS):
        entries = frozen[key]
        if not isinstance(entries, list) or not entries:
            _fail("frozen_identities_invalid")
        values = [_text(item, _ID, "frozen_identity_invalid") for item in entries]
        if len(values) != len(set(values)):
            _fail("frozen_identity_duplicate")
        frozen_out[key] = values
    frozen_digest = _sha(value.get("frozen_identities_sha256"), "frozen_identities_digest_invalid")
    if hashlib.sha256(_canonical(frozen_out)).hexdigest() != frozen_digest:
        _fail("frozen_identities_digest_mismatch")
    return {**value, **materials, "product_files": product_files, "budgets": dict(budgets), "holdout_pins": _holdouts(value["holdout_pins"]), "frozen_identities": frozen_out, "frozen_identities_sha256": frozen_digest}


def build_acceptance_registration(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a digest-bound registration manifest without filesystem or process I/O."""
    parsed = _payload(payload)
    return {**parsed, "registration_sha256": hashlib.sha256(_canonical(parsed)).hexdigest()}


def parse_acceptance_registration(value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        value = _parse_json(value)
    if not isinstance(value, Mapping) or set(value) != _REGISTRATION_KEYS | {"registration_sha256"}:
        _fail("registration_schema_invalid")
    digest = _sha(value.get("registration_sha256"), "registration_digest_invalid")
    parsed = _payload({key: item for key, item in value.items() if key != "registration_sha256"})
    if hashlib.sha256(_canonical(parsed)).hexdigest() != digest:
        _fail("registration_digest_mismatch")
    expected = {**parsed, "registration_sha256": digest}
    if _canonical(value) != _canonical(expected):
        _fail("registration_noncanonical")
    return expected


def build_registration_seal(registration: Mapping[str, Any] | str) -> dict[str, Any]:
    """Build the seal before committing the manifest and seal files."""
    parsed = parse_acceptance_registration(registration)
    payload = {
        "schema_version": SCHEMA_VERSION, "scope": SEAL_SCOPE,
        "registration_sha256": parsed["registration_sha256"],
        "registration_id": parsed["registration_id"], "campaign_id": parsed["campaign_id"],
        "attempt_id": parsed["attempt_id"], "product_commit": parsed["product_commit"],
        "campaign_root": parsed["campaign_root"],
    }
    return {**payload, "seal_sha256": hashlib.sha256(_canonical(payload)).hexdigest()}


def parse_registration_seal(value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        value = _parse_json(value)
    if not isinstance(value, Mapping) or set(value) != _SEAL_KEYS:
        _fail("seal_schema_invalid")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("scope") != SEAL_SCOPE:
        _fail("seal_schema_invalid")
    _sha(value.get("registration_sha256"), "seal_registration_digest_invalid")
    for key in ("registration_id", "campaign_id"):
        _text(value.get(key), _ID, "seal_identity_invalid")
    _text(value.get("attempt_id"), _ID, "seal_identity_invalid")
    if value["attempt_id"] != "attempt-001":
        _fail("invalid_attempt_id")
    _text(value.get("product_commit"), _COMMIT, "seal_product_commit_invalid")
    _text(value.get("campaign_root"), _ROOT, "seal_campaign_root_invalid")
    digest = _sha(value.get("seal_sha256"), "seal_digest_invalid")
    payload = {key: item for key, item in value.items() if key != "seal_sha256"}
    if hashlib.sha256(_canonical(payload)).hexdigest() != digest:
        _fail("seal_digest_mismatch")
    if _canonical(value) != _canonical({**payload, "seal_sha256": digest}):
        _fail("seal_noncanonical")
    return dict(value)


def _frozen_ids(value: Sequence[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, bytes)) or len(value) > MAX_FROZEN_IDENTITIES:
        _fail("frozen_identities_invalid")
    result: set[str] = set()
    for item in value:
        _text(item, _ID, "frozen_identity_invalid")
        if item in result:
            _fail("frozen_identity_duplicate")
        result.add(item)
    return result


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _read_regular(path: Path, maximum: int = MAX_REGISTRATION_BYTES) -> bytes:
    try:
        with ExitStack() as stack:
            chain = DirectoryChain(path.parent, "preflight_file_changed")
            stack.callback(chain.close)
            before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                _fail("preflight_file_invalid")
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=chain.fd,
            )
            stack.callback(os.close, descriptor)
            if _fingerprint(before) != _fingerprint(os.fstat(descriptor)):
                _fail("preflight_file_changed")
            chunks = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
            if (len(content) != before.st_size or len(content) > maximum
                    or _fingerprint(before) != _fingerprint(after)
                    or _fingerprint(after) != _fingerprint(named)):
                _fail("preflight_file_changed")
            chain.check()
            return content
    except CandidateWorkspaceError:
        _fail("preflight_file_changed")
    except OSError:
        _fail("preflight_file_unavailable")


def _git(checkout: Path, *args: str, check: bool = True) -> bytes | tuple[int, bytes]:
    try:
        result = subprocess.run(["git", *args], cwd=checkout, check=False, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        _fail("preflight_git_unavailable")
    if check and b"\x00" in result.stdout:
        _fail("preflight_git_invalid")
    if check and result.returncode:
        _fail("preflight_git_invalid")
    if check:
        return result.stdout
    return result.returncode, result.stdout


def _committed_regular(checkout: Path, revision: str, path: str) -> bool:
    code, listing = _git(
        checkout, "--literal-pathspecs", "ls-tree", "-z", revision, "--", path,
        check=False,
    )
    if code:
        _fail("preflight_git_invalid")
    entries = listing.split(b"\x00")
    if len(entries) != 2 or entries[1] or b"\t" not in entries[0]:
        return False
    descriptor, listed_path = entries[0].split(b"\t", 1)
    fields = descriptor.split(b" ")
    return (
        listed_path == path.encode("utf-8") and len(fields) == 3
        and fields[0] in {b"100644", b"100755"} and fields[1] == b"blob"
    )


def preflight_acceptance_registration(
    registration_path: str | os.PathLike[str],
    seal_path: str | os.PathLike[str],
    *,
    checkout_root: str | os.PathLike[str],
    campaign_parent: str | os.PathLike[str],
    frozen_identities: Sequence[str] | None = None,
    origin_ref: str = "origin/main",
) -> dict[str, Any]:
    """Read-only preflight over committed registration/seal and checkout state."""
    checkout = Path(checkout_root).expanduser().absolute()
    parent = Path(campaign_parent).expanduser().absolute()
    manifest_path = Path(registration_path).expanduser().absolute()
    seal_file = Path(seal_path).expanduser().absolute()
    if not checkout.is_dir() or checkout.is_symlink() or not parent.is_dir() or parent.is_symlink():
        _fail("preflight_path_invalid")
    if type(origin_ref) is not str or _REF.fullmatch(origin_ref) is None or ".." in origin_ref.split("/"):
        _fail("preflight_ref_invalid")
    try:
        manifest_rel = manifest_path.relative_to(checkout).as_posix()
        seal_rel = seal_file.relative_to(checkout).as_posix()
    except ValueError:
        _fail("preflight_path_invalid")
    _relative(manifest_rel, "preflight_path_invalid")
    _relative(seal_rel, "preflight_path_invalid")
    manifest_bytes = _read_regular(manifest_path)
    seal_bytes = _read_regular(seal_file)
    try:
        manifest = parse_acceptance_registration(manifest_bytes.decode("utf-8"))
        seal = parse_registration_seal(seal_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        _fail("preflight_file_invalid")
    if seal["registration_sha256"] != manifest["registration_sha256"] or any(seal[key] != manifest[key] for key in ("registration_id", "campaign_id", "attempt_id", "product_commit", "campaign_root")):
        _fail("seal_registration_mismatch")
    frozen = {item for values in manifest["frozen_identities"].values() for item in values}
    if frozen_identities is not None:
        frozen.update(_frozen_ids(frozen_identities))
    if {manifest["registration_id"], manifest["campaign_id"], manifest["campaign_root"]} & frozen:
        _fail("identity_reused")
    head = _git(checkout, "rev-parse", "HEAD").strip()
    origin = _git(checkout, "rev-parse", "--verify", origin_ref).strip()
    status = _git(checkout, "status", "--porcelain", "--untracked-files=all")
    if head != origin:
        _fail("checkout_not_pushed")
    if status:
        _fail("checkout_dirty")
    pinned_head = head.decode("ascii")
    materials = [manifest[key] for key in (
        "task_material", "input_material", "evaluator_material", "evaluator_profile_material",
    )]
    materials.extend(pin[key] for pin in manifest["holdout_pins"] for key in ("input", "expected"))
    tracked_code, _tracked = _git(
        checkout, "--literal-pathspecs", "ls-files", "--error-unmatch", "--",
        manifest_rel, seal_rel,
        *(item["path"] for item in (*manifest["product_files"], *materials)), check=False,
    )
    if tracked_code:
        _fail("registration_files_untracked")
    if not all(_committed_regular(checkout, pinned_head, path) for path in (manifest_rel, seal_rel)):
        _fail("registration_bytes_not_tracked")
    if _git(checkout, "show", f"{pinned_head}:{manifest_rel}") != manifest_bytes or _git(checkout, "show", f"{pinned_head}:{seal_rel}") != seal_bytes:
        _fail("registration_bytes_not_tracked")
    ancestor_code, _ancestor = _git(
        checkout, "merge-base", "--is-ancestor", manifest["product_commit"], head, check=False,
    )
    if ancestor_code:
        _fail("product_commit_invalid")
    for pins, code, revisions in (
        (manifest["product_files"], "product_file_drift", (manifest["product_commit"], pinned_head)),
        (materials, "material_file_drift", (pinned_head,)),
    ):
        for item in pins:
            content = _read_regular(checkout / item["path"], MAX_PRODUCT_FILE_BYTES)
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                _fail(code)
            for revision in revisions:
                if not _committed_regular(checkout, revision, item["path"]):
                    _fail(code)
                blob_code, blob = _git(
                    checkout, "cat-file", "blob", f"{revision}:{item['path']}", check=False,
                )
                if blob_code or blob != content:
                    _fail(code)
    if (_git(checkout, "rev-parse", "HEAD").strip() != head
            or _git(checkout, "rev-parse", "--verify", origin_ref).strip() != origin
            or _git(checkout, "status", "--porcelain", "--untracked-files=all")):
        _fail("checkout_changed_during_preflight")
    root = parent / manifest["campaign_root"]
    if root.parent != parent or root.name != manifest["campaign_root"] or os.path.lexists(root):
        _fail("campaign_root_not_fresh")
    checks = {
        "product_commit": True, "head_equals_origin": True, "worktree_clean": True,
        "registration_tracked": True, "seal_tracked": True, "manifest_canonical": True,
        "product_files_unchanged": True, "campaign_root_absent": True, "identity_fresh": True,
        "materials_tracked": True, "material_files_unchanged": True,
    }
    return {"schema_version": SCHEMA_VERSION, "scope": PREFLIGHT_SCOPE, "registration_sha256": manifest["registration_sha256"], "status": "ready", "checks": checks, "first_problem": None, "head_commit": head.decode("ascii"), "origin_commit": origin.decode("ascii"), "manifest_path": manifest_rel, "seal_path": seal_rel}


__all__ = [
    "MAX_REGISTRATION_BYTES", "REGISTRATION_SCOPE", "SEAL_SCOPE", "AcceptanceRegistrationError",
    "build_acceptance_registration", "build_registration_seal", "parse_acceptance_registration",
    "parse_registration_seal", "preflight_acceptance_registration",
]
