"""Provider-free, create-only claim for one revalidated acceptance attempt.

The gate is the last local boundary before a future provider runner.  It consumes a
``ready`` result from :func:`acceptance_launch.revalidate_acceptance_campaign`, rereads
and verifies the retained admission receipt, then creates exactly one
``attempt-started.json`` file with ``O_EXCL``.  It never starts a provider, writes a
request, invokes a model, or repairs an incomplete claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._benchmark_files import BenchmarkFileError, absolute_path, read_regular_file
from .acceptance_registration import MAX_PRODUCT_FILE_BYTES, _canonical

_MAX_RECEIPT_BYTES = 128 * 1024
_SCHEMA = "1"
_SCOPE = "acceptance_attempt_claim"
_ADMISSION_SCOPE = "acceptance_campaign_admission"
_CLAIM_FILE = "attempt-started.json"


class AcceptanceAttemptGateError(ValueError):
    """Fixed public failure code for the provider-free single-attempt gate."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and code.replace("_", "").isalnum() else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceAttemptGateError(code)


def _canonical_bounded(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = _canonical(value)
    except Exception as exc:
        raise AcceptanceAttemptGateError("attempt_claim_invalid") from exc
    if len(encoded) > _MAX_RECEIPT_BYTES:
        _fail("attempt_claim_too_large")
    return encoded


def _parse_canonical_object(raw: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail(code)
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _value: _fail(code))
    except AcceptanceAttemptGateError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail(code)
    if not isinstance(value, dict) or _canonical_bounded(value) != raw:
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail(code)
    return value


def _identity(value: object, code: str) -> tuple[int, int]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(item) is not int or item < 0 for item in value)):
        _fail(code)
    return int(value[0]), int(value[1])


def _read_admission(root: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = read_regular_file(root / "admission.json", MAX_PRODUCT_FILE_BYTES, exact_size=False)
    except (BenchmarkFileError, OSError) as exc:
        raise AcceptanceAttemptGateError("attempt_admission_unavailable") from exc
    admission = _parse_canonical_object(raw, "attempt_admission_invalid")
    required = {
        "schema_version", "scope", "status", "provider_started", "registration_id",
        "campaign_id", "attempt_id", "campaign_root", "registration_sha256", "product_commit",
        "seal_sha256", "head_commit", "remote_commit", "root_device", "root_inode",
        "parent_device", "parent_inode", "files", "admission_sha256",
    }
    if (set(admission) != required or admission.get("schema_version") != _SCHEMA
            or admission.get("scope") != _ADMISSION_SCOPE
            or admission.get("status") != "prepared"
            or admission.get("provider_started") is not False):
        _fail("attempt_admission_invalid")
    digest = _sha(admission.get("admission_sha256"), "attempt_admission_invalid")
    payload = {key: value for key, value in admission.items() if key != "admission_sha256"}
    if hashlib.sha256(_canonical_bounded(payload)).hexdigest() != digest:
        _fail("attempt_admission_invalid")
    for key in ("registration_sha256", "seal_sha256"):
        _sha(admission.get(key), "attempt_admission_invalid")
    for key in ("root_device", "root_inode", "parent_device", "parent_inode"):
        if type(admission.get(key)) is not int or admission[key] < 0:
            _fail("attempt_admission_invalid")
    for key in ("registration_id", "campaign_id", "attempt_id", "campaign_root", "product_commit", "head_commit", "remote_commit"):
        if type(admission.get(key)) is not str or not admission[key]:
            _fail("attempt_admission_invalid")
    if not isinstance(admission.get("files"), list) or not admission["files"]:
        _fail("attempt_admission_invalid")
    return admission, raw


def _write_create_only(root_fd: int, content: bytes) -> tuple[int, int]:
    try:
        fd = os.open(
            _CLAIM_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=root_fd,
        )
    except FileExistsError:
        _fail("attempt_claim_exists")
    except OSError as exc:
        raise AcceptanceAttemptGateError("attempt_claim_unavailable") from exc
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(content)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                _fail("attempt_claim_write_failed")
            view = view[count:]
        os.fsync(fd)
        held = os.fstat(fd)
        named = os.stat(_CLAIM_FILE, dir_fd=root_fd, follow_symlinks=False)
        if (not stat.S_ISREG(held.st_mode) or held.st_nlink != 1
                or stat.S_IMODE(held.st_mode) != 0o600
                or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                or held.st_size != len(content)):
            _fail("attempt_claim_changed")
        return held.st_dev, held.st_ino
    finally:
        os.close(fd)


def claim_acceptance_attempt(
    revalidated: Mapping[str, Any], *, campaign_parent: str | os.PathLike[str],
) -> dict[str, Any]:
    """Create the sole local attempt claim after a successful campaign revalidation.

    ``revalidated`` must be the unmodified result returned by
    ``revalidate_acceptance_campaign``.  The persisted admission is reread and compared
    byte-for-byte before the create-only claim.  A second call, a mismatched result, or
    any existing claim fails without replacing or repairing files.  This function has no
    provider or model side effects.
    """
    if not isinstance(revalidated, Mapping) or revalidated.get("status") != "ready" or revalidated.get("launch_allowed") is not True:
        _fail("attempt_revalidation_required")
    admission = revalidated.get("admission")
    if not isinstance(admission, Mapping):
        _fail("attempt_revalidation_required")
    try:
        parent = absolute_path(campaign_parent)
        root_name = admission.get("campaign_root")
        if type(root_name) is not str or not root_name or "/" in root_name or root_name in {".", ".."}:
            _fail("attempt_admission_invalid")
        root = parent / root_name
        root_info = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_IMODE(root_info.st_mode) != 0o700:
            _fail("attempt_admission_invalid")
        persisted, admission_raw = _read_admission(root)
        if dict(admission) != persisted:
            _fail("attempt_admission_mismatch")
        if revalidated.get("remote_commit") != persisted.get("remote_commit"):
            _fail("attempt_admission_mismatch")
        if (persisted.get("root_device"), persisted.get("root_inode")) != (root_info.st_dev, root_info.st_ino):
            _fail("attempt_admission_invalid")
        expected_parent = (persisted.get("parent_device"), persisted.get("parent_inode"))
        parent_info = os.stat(parent, follow_symlinks=False)
        if expected_parent != (parent_info.st_dev, parent_info.st_ino):
            _fail("attempt_admission_invalid")
        # The claim is intentionally a separate create-only publication.  It records the
        # local claim boundary and explicitly states that no provider request has occurred.
        claim = {
            "schema_version": _SCHEMA,
            "scope": _SCOPE,
            "status": "attempt_started",
            "attempt_claimed": True,
            "provider_started": False,
            "provider_call_made": False,
            "registration_id": persisted["registration_id"],
            "campaign_id": persisted["campaign_id"],
            "attempt_id": persisted["attempt_id"],
            "campaign_root": persisted["campaign_root"],
            "registration_sha256": persisted["registration_sha256"],
            "admission_sha256": persisted["admission_sha256"],
            "product_commit": persisted["product_commit"],
            "remote_commit": persisted["remote_commit"],
            "root_device": root_info.st_dev,
            "root_inode": root_info.st_ino,
            "parent_device": parent_info.st_dev,
            "parent_inode": parent_info.st_ino,
            "admission_bytes_sha256": hashlib.sha256(admission_raw).hexdigest(),
        }
        claim["attempt_claim_sha256"] = hashlib.sha256(_canonical_bounded(claim)).hexdigest()
        content = _canonical_bounded(claim)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != (root_info.st_dev, root_info.st_ino):
                _fail("attempt_admission_invalid")
            _write_create_only(root_fd, content)
            os.fsync(root_fd)
            final = os.stat(root, follow_symlinks=False)
            if (final.st_dev, final.st_ino) != (root_info.st_dev, root_info.st_ino):
                _fail("attempt_claim_changed")
        finally:
            os.close(root_fd)
        return claim
    except AcceptanceAttemptGateError:
        raise
    except (BenchmarkFileError, OSError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise AcceptanceAttemptGateError("attempt_claim_unavailable") from exc


__all__ = ["AcceptanceAttemptGateError", "claim_acceptance_attempt"]
