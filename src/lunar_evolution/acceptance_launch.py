"""Prepare one fresh acceptance campaign without launching a provider or solve."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain
from .acceptance_registration import (
    MAX_PRODUCT_FILE_BYTES,
    AcceptanceRegistrationError,
    _canonical,
    _fingerprint,
    _git,
    _read_regular,
    build_registration_seal,
    parse_acceptance_registration,
    parse_registration_seal,
    preflight_acceptance_registration,
)
from .candidate_workspace_plan import CandidateWorkspaceError

REMOTE_TIMEOUT_SECONDS = 10
_REMOTE_REF = b"refs/heads/main"


class AcceptanceCampaignError(AcceptanceRegistrationError):
    """A fixed admission reason without Git diagnostics or endpoint values."""


def _fail(code: str) -> None:
    raise AcceptanceCampaignError(code)


def _remote_main(checkout: Path) -> str:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", _REMOTE_REF.decode("ascii")],
            cwd=checkout, stdin=subprocess.DEVNULL, capture_output=True, check=False,
            timeout=REMOTE_TIMEOUT_SECONDS, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        _fail("remote_main_unavailable")
    if result.returncode:
        _fail("remote_main_unavailable")
    match = re.fullmatch(rb"([0-9a-f]{40}|[0-9a-f]{64})\trefs/heads/main\n", result.stdout)
    if match is None:
        _fail("remote_main_invalid")
    return match[1].decode("ascii")


def _material_snapshots(registration: dict, checkout: Path) -> dict[str, bytes]:
    pins = {
        "materials/task.bin": registration["task_material"],
        "materials/input.bin": registration["input_material"],
        "materials/evaluator-criteria.bin": registration["evaluator_material"],
        "materials/profile-criteria.bin": registration["evaluator_profile_material"],
    }
    for holdout in registration["holdout_pins"]:
        for kind in ("input", "expected"):
            pins[f"materials/holdout-{holdout['ordinal']:02d}-{kind}.bin"] = holdout[kind]
    snapshots = {}
    for name, pin in pins.items():
        content = _read_regular(checkout / pin["path"], MAX_PRODUCT_FILE_BYTES)
        if len(content) != pin["size"] or hashlib.sha256(content).hexdigest() != pin["sha256"]:
            _fail("material_file_drift")
        snapshots[name] = content
    return snapshots


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _check_root(parent: DirectoryChain, name: str, descriptor: int) -> None:
    parent.check()
    named = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    held = os.fstat(descriptor)
    if (not stat.S_ISDIR(named.st_mode) or _identity(named) != _identity(held)
            or stat.S_IMODE(held.st_mode) != 0o700):
        _fail("campaign_root_changed")


def _write_new(descriptor: int, name: str, content: bytes) -> tuple[int, ...]:
    target = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600, dir_fd=descriptor,
    )
    try:
        os.fchmod(target, 0o600)
        view = memoryview(content)
        while view:
            count = os.write(target, view)
            if count <= 0:
                _fail("campaign_write_failed")
            view = view[count:]
        os.fsync(target)
        held = os.fstat(target)
        named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or held.st_nlink != 1
                or held.st_size != len(content) or stat.S_IMODE(held.st_mode) != 0o600
                or _fingerprint(held) != _fingerprint(named)):
            _fail("campaign_file_changed")
        return _fingerprint(held)
    finally:
        os.close(target)


def _check_materials(descriptor: int, materials: int) -> None:
    held = os.fstat(materials)
    named = os.stat("materials", dir_fd=descriptor, follow_symlinks=False)
    if (not stat.S_ISDIR(named.st_mode) or _identity(held) != _identity(named)
            or stat.S_IMODE(held.st_mode) != 0o700):
        _fail("campaign_materials_changed")


def _check_inventory(descriptor: int, expected: set[str]) -> None:
    seen = set()
    with os.scandir(descriptor) as entries:
        for entry in entries:
            if entry.name not in expected or entry.name in seen:
                _fail("campaign_file_changed")
            seen.add(entry.name)
    if seen != expected:
        _fail("campaign_file_changed")


def _check_evidence(
    descriptor: int, materials: int, snapshots: dict[str, bytes],
    fingerprints: dict[str, tuple[int, ...]],
) -> None:
    _check_materials(descriptor, materials)
    _check_inventory(descriptor, {"materials", *(p for p in snapshots if "/" not in p)})
    _check_inventory(materials, {p.split("/")[1] for p in snapshots if "/" in p})
    for path, expected in sorted(snapshots.items()):
        parent, name = (materials, path.split("/")[1]) if "/" in path else (descriptor, path)
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _fingerprint(before) != fingerprints[path] or before.st_nlink != 1:
            _fail("campaign_file_changed")
        target = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent,
        )
        try:
            if _fingerprint(os.fstat(target)) != fingerprints[path]:
                _fail("campaign_file_changed")
            digest, size, remaining = hashlib.sha256(), 0, len(expected) + 1
            while remaining:
                chunk = os.read(target, min(remaining, 65536))
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                remaining -= len(chunk)
            held = os.fstat(target)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (size != len(expected) or digest.digest() != hashlib.sha256(expected).digest()
                    or held.st_nlink != 1 or named.st_nlink != 1
                    or _fingerprint(held) != fingerprints[path]
                    or _fingerprint(named) != fingerprints[path]):
                _fail("campaign_file_changed")
        finally:
            os.close(target)
    _check_materials(descriptor, materials)


def prepare_acceptance_campaign(
    registration_path: str | os.PathLike[str],
    seal_path: str | os.PathLike[str],
    *,
    checkout_root: str | os.PathLike[str],
    campaign_parent: str | os.PathLike[str],
) -> dict[str, Any]:
    """Verify remote main and retain one exclusive admission; never launch or repair."""
    created = False
    try:
        checkout, parent = absolute_path(checkout_root), absolute_path(campaign_parent)
        manifest_path, seal_file = absolute_path(registration_path), absolute_path(seal_path)
        first = preflight_acceptance_registration(
            manifest_path, seal_file, checkout_root=checkout, campaign_parent=parent,
        )
        remote_commit = _remote_main(checkout)
        if remote_commit != first["head_commit"]:
            _fail("remote_main_mismatch")
        manifest_bytes, seal_bytes = _read_regular(manifest_path), _read_regular(seal_file)
        registration = parse_acceptance_registration(manifest_bytes.decode("utf-8"))
        seal = parse_registration_seal(seal_bytes.decode("utf-8"))
        if (registration["registration_sha256"] != first["registration_sha256"]
                or seal != build_registration_seal(registration)):
            _fail("registration_changed_during_admission")
        snapshots = _material_snapshots(registration, checkout)
        second = preflight_acceptance_registration(
            manifest_path, seal_file, checkout_root=checkout, campaign_parent=parent,
        )
        if first != second:
            _fail("checkout_changed_during_admission")
        snapshots.update({
            "registration.json": manifest_bytes,
            "registration-seal.json": seal_bytes,
            "preflight.json": _canonical(second),
            "remote-main.json": _canonical({
                "schema_version": "1", "scope": "acceptance_remote_main",
                "ref": "refs/heads/main", "commit": remote_commit,
            }),
        })
        with ExitStack() as stack:
            chain = DirectoryChain(parent, "campaign_parent_changed")
            stack.callback(chain.close)
            name = registration["campaign_root"]
            chain.check()
            try:
                os.mkdir(name, 0o700, dir_fd=chain.fd)
            except FileExistsError:
                _fail("campaign_root_not_fresh")
            created = True
            before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
            descriptor = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=chain.fd,
            )
            stack.callback(os.close, descriptor)
            if _identity(before) != _identity(os.fstat(descriptor)):
                _fail("campaign_root_changed")
            os.fchmod(descriptor, 0o700)
            _check_root(chain, name, descriptor)
            os.fsync(chain.fd)
            os.mkdir("materials", 0o700, dir_fd=descriptor)
            before = os.stat("materials", dir_fd=descriptor, follow_symlinks=False)
            materials = os.open(
                "materials", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            stack.callback(os.close, materials)
            if _identity(before) != _identity(os.fstat(materials)):
                _fail("campaign_materials_changed")
            os.fchmod(materials, 0o700)
            fingerprints = {}
            for path, content in sorted(snapshots.items()):
                _check_root(chain, name, descriptor)
                if path.startswith("materials/"):
                    _check_materials(descriptor, materials)
                    fingerprints[path] = _write_new(materials, path.split("/")[1], content)
                else:
                    fingerprints[path] = _write_new(descriptor, path, content)
            os.fsync(materials)
            os.fsync(descriptor)
            if (_git(checkout, "rev-parse", "HEAD").strip().decode("ascii") != remote_commit
                    or _git(checkout, "rev-parse", "--verify", "origin/main").strip().decode("ascii") != remote_commit
                    or _git(checkout, "status", "--porcelain", "--untracked-files=all")):
                _fail("checkout_changed_during_admission")
            root_info, parent_info = os.fstat(descriptor), os.fstat(chain.fd)
            receipt = {
                "schema_version": "1", "scope": "acceptance_campaign_admission",
                "status": "prepared", "provider_started": False,
                **{key: registration[key] for key in (
                    "registration_id", "campaign_id", "attempt_id", "campaign_root",
                    "registration_sha256", "product_commit",
                )},
                "seal_sha256": seal["seal_sha256"], "head_commit": second["head_commit"],
                "remote_commit": remote_commit,
                "root_device": root_info.st_dev, "root_inode": root_info.st_ino,
                "parent_device": parent_info.st_dev, "parent_inode": parent_info.st_ino,
                "files": [
                    {"path": path, "size": len(content),
                     "sha256": hashlib.sha256(content).hexdigest()}
                    for path, content in sorted(snapshots.items())
                ],
            }
            receipt["admission_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
            _check_root(chain, name, descriptor)
            _check_evidence(descriptor, materials, snapshots, fingerprints)
            snapshots["admission.json"] = _canonical(receipt)
            fingerprints["admission.json"] = _write_new(
                descriptor, "admission.json", snapshots["admission.json"],
            )
            os.fsync(descriptor)
            os.fsync(chain.fd)
            _check_root(chain, name, descriptor)
            _check_evidence(descriptor, materials, snapshots, fingerprints)
            return receipt
    except (AcceptanceRegistrationError, CandidateWorkspaceError, BenchmarkFileError,
            OSError, UnicodeError) as exc:
        if created:
            raise AcceptanceCampaignError("campaign_admission_incomplete") from None
        if isinstance(exc, AcceptanceRegistrationError):
            raise AcceptanceCampaignError(exc.code) from None
        raise AcceptanceCampaignError("campaign_admission_unavailable") from None



def revalidate_acceptance_campaign(
    registration_path: str | os.PathLike[str],
    seal_path: str | os.PathLike[str],
    *,
    checkout_root: str | os.PathLike[str],
    campaign_parent: str | os.PathLike[str],
) -> dict[str, Any]:
    """Recheck one admitted campaign immediately before a future invocation.

    This is intentionally provider-free: it only validates the committed checkout, remote
    ``main`` and the retained admission evidence.  A true result is a launch gate, never a
    provider call or a claim that an attempt started.
    """
    try:
        checkout, parent = absolute_path(checkout_root), absolute_path(campaign_parent)
        manifest_file, seal_file = absolute_path(registration_path), absolute_path(seal_path)
        first = preflight_acceptance_registration(
            manifest_file, seal_file, checkout_root=checkout, campaign_parent=parent,
            allow_existing_root=True,
        )
        remote_commit = _remote_main(checkout)
        if remote_commit != first["head_commit"] or first["origin_commit"] != remote_commit:
            _fail("remote_main_mismatch")
        manifest = parse_acceptance_registration(_read_regular(manifest_file).decode("utf-8"))
        root = parent / manifest["campaign_root"]
        admission_raw = _read_regular(root / "admission.json", MAX_PRODUCT_FILE_BYTES)
        admission = None
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, value in items:
                if key in parsed:
                    _fail("campaign_admission_incomplete")
                parsed[key] = value
            return parsed

        try:
            admission = json.loads(admission_raw, object_pairs_hook=pairs)
        except (TypeError, ValueError, UnicodeDecodeError):
            _fail("campaign_admission_incomplete")
        if (not isinstance(admission, dict)
                or _canonical(admission) != admission_raw
                or set(admission) != {
                    "schema_version", "scope", "status", "provider_started", "registration_id",
                    "campaign_id", "attempt_id", "campaign_root", "registration_sha256",
                    "product_commit", "seal_sha256", "head_commit", "remote_commit",
                    "root_device", "root_inode", "parent_device", "parent_inode", "files",
                    "admission_sha256",
                }
                or admission.get("schema_version") != "1"
                or admission.get("scope") != "acceptance_campaign_admission"
                or admission.get("status") != "prepared"
                or admission.get("provider_started") is not False):
            _fail("campaign_admission_incomplete")
        digest = admission.get("admission_sha256")
        if type(digest) is not str or hashlib.sha256(_canonical({k: v for k, v in admission.items() if k != "admission_sha256"})).hexdigest() != digest:
            _fail("campaign_admission_incomplete")
        for key in ("registration_id", "campaign_id", "attempt_id", "campaign_root", "registration_sha256", "product_commit"):
            if admission.get(key) != manifest.get(key):
                _fail("campaign_admission_incomplete")
        info = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            _fail("campaign_admission_incomplete")
        if (admission.get("root_device"), admission.get("root_inode")) != (info.st_dev, info.st_ino):
            _fail("campaign_admission_incomplete")
        files = admission.get("files")
        if not isinstance(files, list) or not files:
            _fail("campaign_admission_incomplete")
        expected = set()
        for item in files:
            if (not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}
                    or type(item.get("size")) is not int or item["size"] < 0
                    or type(item.get("sha256")) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
                _fail("campaign_admission_incomplete")
            try:
                relative = item["path"]
                if not isinstance(relative, str):
                    _fail("campaign_admission_incomplete")
                parts = relative.split("/")
                if (not relative or any(part in {"", ".", "..", ".git"} for part in parts)
                        or any(ord(char) < 32 or ord(char) == 127 for char in relative)):
                    _fail("campaign_admission_incomplete")
            except (TypeError, ValueError):
                _fail("campaign_admission_incomplete")
            expected.add(relative)
        if len(expected) != len(files) or "admission.json" in expected:
            _fail("campaign_admission_incomplete")
        expected_root = {"materials", "admission.json", *(p for p in expected if "/" not in p)}
        with os.scandir(root) as entries:
            if {e.name for e in entries} != expected_root:
                _fail("campaign_admission_incomplete")
        for item in files:
            path = item["path"]
            target = root / path
            raw = _read_regular(target, MAX_PRODUCT_FILE_BYTES)
            if len(raw) != item.get("size") or hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                _fail("campaign_admission_incomplete")
            named = os.stat(target, follow_symlinks=False)
            if (not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or stat.S_IMODE(named.st_mode) != 0o600):
                _fail("campaign_admission_incomplete")
        materials_info = os.stat(root / "materials", follow_symlinks=False)
        if (not stat.S_ISDIR(materials_info.st_mode)
                or stat.S_IMODE(materials_info.st_mode) != 0o700):
            _fail("campaign_admission_incomplete")
        if _remote_main(checkout) != remote_commit:
            _fail("remote_main_mismatch")
        final = preflight_acceptance_registration(
            manifest_file, seal_file, checkout_root=checkout, campaign_parent=parent,
            allow_existing_root=True,
        )
        if final != first or final["head_commit"] != remote_commit:
            _fail("checkout_changed_during_admission")
        return {"status": "ready", "launch_allowed": True, "admission": admission, "preflight": final, "remote_commit": remote_commit}
    except AcceptanceCampaignError:
        raise
    except (AcceptanceRegistrationError, BenchmarkFileError, OSError, UnicodeError, ValueError, TypeError):
        raise AcceptanceCampaignError("campaign_admission_incomplete") from None

__all__ = ["AcceptanceCampaignError", "prepare_acceptance_campaign", "revalidate_acceptance_campaign"]
