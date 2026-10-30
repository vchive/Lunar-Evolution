"""Installed, independent pre-gate anchor custody and read-only restart lookup.

The installation reference is supplied by trusted local installation code, never
by channel/packet discovery. Private filesystem custody is a trust assumption;
this module grants no execution, cleanup, immutable-custody or publication claim.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .external_worker_native_lifecycle import WorkerNativeTaskMapping, _lookup
from .external_worker_native_restart import (
    WorkerNativeRestartAnchor,
    _bound,
    _chain_pins,
    _digest,
    _file_pin,
    _key,
    _object,
    _path,
    _report,
    _verify_chain,
    inspect_native_restart,
)
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey
from .external_worker_wrapper import _publish, _read_at, parse_worker_json, worker_json

_PROTOCOL = "lunar-installed-worker-native-vault-v1"
_DOMAIN = b"lunar-installed-worker-native-vault-v1\0"
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_MAX = 256 * 1024
_INSTALL_FIELDS = {"protocol", "kind", "directory", "directory_chain", "profile_sha256",
                   "key_sha256", *_IDENTITY}
_RECORD_FIELDS = {"protocol", "kind", "profile_sha256", "lookup", "context", "mapping",
                  "anchor", "production_admission", *_IDENTITY}


class WorkerNativeVaultError(ValueError):
    """Fixed errors without private paths, original authorization or key bytes."""


def _fail(code: str) -> None:
    raise WorkerNativeVaultError("worker_native_vault_" + code)


@dataclass(frozen=True, slots=True)
class InstalledWorkerNativeVault:
    """Original trusted installation bytes, preserved outside the episode store.

    Constructing this object from a worker request or packet is not a supported
    installation. There is no public from-disk/current-packet installation loader.
    A host's trusted installation retains/delivers these original bytes on restart.
    """

    canonical_bytes: bytes = field(repr=False)


def _private_chain(chain: DirectoryChain) -> None:
    pins = _chain_pins(chain)
    for _dev, _ino, mode, uid, _gid in pins:
        sticky_root = uid == 0 and mode & stat.S_ISVTX
        if (not stat.S_ISDIR(mode) or uid not in {0, os.geteuid()}
                or (mode & 0o022 and not sticky_root)):
            _fail("installation_chain_refused")
    leaf = os.fstat(chain.fd)
    if leaf.st_uid != os.geteuid() or stat.S_IMODE(leaf.st_mode) != 0o700:
        _fail("installation_directory_refused")


def capture_installed_native_vault(
    directory: Path, *, original_directory_chain: DirectoryChain,
    key: WorkerOriginKey, profile_sha256: str,
) -> InstalledWorkerNativeVault:
    """Trusted installer only: retain its original held directory, not an anchor.

    This is explicit initial installation, not a runtime repair/discovery path.
    The installer must preserve this reference independently across processes.
    No directory or account is provisioned and no production readiness is granted.
    """
    try:
        key = _key(key)
        key_baseline = tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key)
        if (type(original_directory_chain) is not DirectoryChain
                or not isinstance(directory, Path)
                or _path(str(directory)) != directory
                or tuple(link[1] for link in original_directory_chain.links) != directory.parts[1:]):
            _fail("installation_invalid")
        _private_chain(original_directory_chain)
        reference = InstalledWorkerNativeVault(worker_json({
            "protocol": _PROTOCOL, "kind": "original-installation", "directory": str(directory),
            "directory_chain": _chain_pins(original_directory_chain),
            "profile_sha256": _digest(profile_sha256),
            "key_sha256": hashlib.sha256(key.secret_key).hexdigest(),
            **{name: getattr(key, name) for name in _IDENTITY},
        }))
        _private_chain(original_directory_chain)
        _key(key)
        if ((tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key)) != key_baseline):
            _fail("installation_key_drift")
        return reference
    except Exception:  # noqa: BLE001 - installation boundary hides private paths and key details
        raise WorkerNativeVaultError("worker_native_vault_installation_refused") from None


def _installation(
    installation: InstalledWorkerNativeVault, key: WorkerOriginKey, profile: str,
) -> dict:
    if (type(installation) is not InstalledWorkerNativeVault
            or type(installation.canonical_bytes) is not bytes):
        _fail("installation_required")
    value = _object(parse_worker_json(installation.canonical_bytes, 65536), _INSTALL_FIELDS)
    _key(key)
    path = _path(value["directory"])
    if (value["protocol"] != _PROTOCOL or value["kind"] != "original-installation"
            or value["profile_sha256"] != _digest(profile)
            or any(value[name] != getattr(key, name) for name in _IDENTITY)
            or not hmac.compare_digest(_digest(value["key_sha256"]),
                                       hashlib.sha256(key.secret_key).hexdigest())
            or type(value["directory_chain"]) is not list
            or len(value["directory_chain"]) != len(path.parts)):
        _fail("installation_drift")
    return value


def _open(installation: InstalledWorkerNativeVault, key: WorkerOriginKey, profile: str):
    value = _installation(installation, key, profile)
    chain = DirectoryChain(_path(value["directory"]), "worker_native_vault_directory_drift")
    try:
        _verify_chain(chain, value["directory_chain"])
        _private_chain(chain)
    except BaseException:
        chain.close()
        raise
    return value, chain


def _originals(raw: bytes, context: WorkerOriginContext, mapping: WorkerNativeTaskMapping,
               profile: str) -> dict:
    lookup = _lookup(raw)
    if type(context) is not WorkerOriginContext or type(mapping) is not WorkerNativeTaskMapping:
        _fail("original_assignment_required")
    context.__post_init__()
    mapping.__post_init__()
    if (lookup["context"] != context.to_dict() or lookup["profile_sha256"] != _digest(profile)
            or (mapping.worker_run_id, mapping.worker_task_id, mapping.episode_id)
            != (context.run_id, context.task_id, context.episode_id)):
        _fail("original_assignment_drift")
    return lookup


def _anchor(anchor: WorkerNativeRestartAnchor, value: dict, lookup: dict) -> dict:
    if type(anchor) is not WorkerNativeRestartAnchor or type(anchor.canonical_bytes) is not bytes:
        _fail("original_anchor_required")
    parsed = _object(parse_worker_json(anchor.canonical_bytes, 65536), {
        "protocol", "kind", "profile_sha256", "lookup_sha256", "worker_path", "worker_chain",
        "packet_identity", "complete_identity", *_IDENTITY,
    })
    if (parsed["protocol"] != "lunar-worker-native-restart-v1"
            or parsed["kind"] != "trusted-original-anchor"
            or parsed["lookup_sha256"] != hashlib.sha256(worker_json(lookup)).hexdigest()
            or parsed["profile_sha256"] != value["profile_sha256"]
            or any(parsed[name] != value[name] for name in _IDENTITY)):
        _fail("original_anchor_drift")
    _file_pin(parsed["packet_identity"])
    _file_pin(parsed["complete_identity"])
    vault, worker = _path(value["directory"]), _path(parsed["worker_path"])
    if vault == worker or vault in worker.parents or worker in vault.parents:
        _fail("independent_store_required")
    return parsed


def check_installed_vault_separation(
    installation: InstalledWorkerNativeVault, *, key: WorkerOriginKey,
    profile_sha256: str, private_roots: tuple[Path, ...],
) -> None:
    """The installed bridge must keep vault custody outside native/episode stores."""
    value, chain = _open(installation, key, profile_sha256)
    try:
        vault = _path(value["directory"])
        leaf = os.fstat(chain.fd)
        for root in private_roots:
            root = _path(str(root))
            if vault == root or vault in root.parents or root in vault.parents:
                _fail("independent_store_required")
            if root.exists():
                info = os.stat(root, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == (leaf.st_dev, leaf.st_ino):
                    _fail("independent_store_required")
        _verify_chain(chain, value["directory_chain"])
    finally:
        chain.close()


def retain_installed_native_anchor(
    installation: InstalledWorkerNativeVault, anchor: WorkerNativeRestartAnchor, raw: bytes, *,
    key: WorkerOriginKey, expected_context: WorkerOriginContext,
    expected_mapping: WorkerNativeTaskMapping, expected_profile_sha256: str,
) -> None:
    """Original pre-gate observer only: create, fsync and recheck independent custody."""
    chain = None
    try:
        baseline = installation.canonical_bytes
        originals = worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()})
        lookup = _originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = _open(installation, key, expected_profile_sha256)
        original_anchor = anchor.canonical_bytes
        parsed = _anchor(anchor, value, lookup)
        unsigned = {"protocol": _PROTOCOL, "kind": "original-anchor-custody",
                    "profile_sha256": expected_profile_sha256, "lookup": lookup,
                    "context": expected_context.to_dict(), "mapping": expected_mapping.to_dict(),
                    "anchor": parsed, "production_admission": False,
                    **{name: value[name] for name in _IDENTITY}}
        mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        record = worker_json({**unsigned, "mac_sha256": mac})
        if len(record) > _MAX:
            _fail("record_bounds")
        name = hashlib.sha256(raw).hexdigest() + ".json"
        pin = _file_pin(_publish(chain.fd, name, record, capture_identity=True))
        if _bound(chain, name, pin) != record:
            _fail("custody_drift")
        _verify_chain(chain, value["directory_chain"])
        _private_chain(chain)
        if (installation.canonical_bytes != baseline or _installation(installation, key, expected_profile_sha256) != value
                or anchor.canonical_bytes != original_anchor
                or worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}) != originals):
            _fail("originals_drift")
    except Exception:  # noqa: BLE001 - pre-gate custody refuses all failures without private details
        raise WorkerNativeVaultError("worker_native_vault_retention_refused") from None
    finally:
        if chain is not None:
            chain.close()


def inspect_installed_native_restart(
    raw: bytes, *, installation: InstalledWorkerNativeVault | None, key: WorkerOriginKey,
    expected_context: WorkerOriginContext, expected_mapping: WorkerNativeTaskMapping,
    expected_profile_sha256: str,
) -> dict:
    """Fixed installed lookup: independently supplied originals; no launch/repair."""
    chain = None
    try:
        lookup = _originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = _open(installation, key, expected_profile_sha256)
        baseline = installation.canonical_bytes
        originals = worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()})
        name = hashlib.sha256(raw).hexdigest() + ".json"
        before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        record = _read_at(chain.fd, name, _MAX)
        parsed = _object(parse_worker_json(record, _MAX), _RECORD_FIELDS | {"mac_sha256"})
        unsigned = {name: item for name, item in parsed.items() if name != "mac_sha256"}
        expected_mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        if (not hmac.compare_digest(_digest(parsed["mac_sha256"]), expected_mac)
                or parsed["protocol"] != _PROTOCOL or parsed["kind"] != "original-anchor-custody"
                or parsed["production_admission"] is not False
                or parsed["lookup"] != lookup or parsed["context"] != expected_context.to_dict()
                or parsed["mapping"] != expected_mapping.to_dict()
                or parsed["profile_sha256"] != expected_profile_sha256
                or any(parsed[name] != value[name] for name in _IDENTITY)):
            _fail("custody_record_drift")
        anchor = WorkerNativeRestartAnchor(worker_json(parsed["anchor"]))
        _anchor(anchor, value, lookup)
        result = inspect_native_restart(
            anchor, raw, key=key, expected_context=expected_context,
            expected_mapping=expected_mapping, expected_profile_sha256=expected_profile_sha256,
        )
        # This current vault-entry identity checks this trusted read only. It is
        # never substituted for the original packet/completion creator pins.
        after = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        stable = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                               info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (stable(before) != stable(after) or _read_at(chain.fd, name, _MAX) != record
                or installation.canonical_bytes != baseline
                or _installation(installation, key, expected_profile_sha256) != value
                or worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}) != originals):
            _fail("custody_read_drift")
        _verify_chain(chain, value["directory_chain"])
        _private_chain(chain)
        if (installation.canonical_bytes != baseline
                or _installation(installation, key, expected_profile_sha256) != value):
            _fail("custody_read_drift")
        return {**result, "independent_anchor_custody_observed": True, "production_admission": False}
    except Exception:  # noqa: BLE001 - read-only restart exposes only a fixed conservative report
        return {**_report(raw, "installed_original_custody_unavailable_or_drift"),
                "independent_anchor_custody_observed": False, "production_admission": False}
    finally:
        if chain is not None:
            chain.close()
