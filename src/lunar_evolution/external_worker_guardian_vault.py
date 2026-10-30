"""Explicit installed guardian-reference sidecar; original native vault wire stays V1.

This independent private store preserves original creator-delivered data, not
live process capabilities or accepted production/cleanup authority.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import stat
import time
from collections.abc import Callable

from . import external_worker_native_vault as native_vault
from ._candidate_workspace_io import DirectoryChain
from .external_worker_native_lifecycle import WorkerNativeTaskMapping
from .external_worker_native_restart import (
    WorkerNativeRestartAnchor,
    _bound,
    _digest,
    _file_pin,
    _native_wire,
    _object,
    _path,
    _verify_chain,
)
from .external_worker_native_restart import (
    _native as _restore_native,
)
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey
from .external_worker_wrapper import _read_at, parse_worker_json, worker_json
from .native_guardian_custody import _json as _guardian_json
from .native_guardian_custody import _parse as _guardian_parse
from .native_guardian_registration import (
    GuardianNativeRegistrationReference,
    inspect_registered_native_guardian_custody,
)
from .native_guardian_registration import (
    _native as _native_projection,
)
from .native_trusted_attempt import NativeTrustedRegisteredContext

_PROTOCOL = "lunar-installed-worker-guardian-vault-v1"
_DOMAIN = b"lunar-installed-worker-guardian-vault-v1\0"
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_MAX = 256 * 1024
_FIELDS = {"protocol", "kind", "profile_sha256", "lookup", "context", "mapping",
           "native_anchor", "guardian_reference", "native_vault_sha256", *_IDENTITY,
           "production_admission", "native_success", "publication_authority", "cleanup_authority"}
_FALSE = {"production_admission": False, "native_success": False,
          "publication_authority": False, "cleanup_authority": False}


class WorkerGuardianVaultError(ValueError):
    """Fixed errors without original paths, authorization or signing keys."""


def _fail() -> None:
    raise WorkerGuardianVaultError("worker_guardian_vault_custody_refused")


def _stable(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _name(raw: bytes) -> str:
    return "guardian-" + hashlib.sha256(raw).hexdigest() + ".json"


def _read_stable(chain: DirectoryChain, name: str, maximum: int) -> bytes:
    chain.check()
    before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
    raw = _read_at(chain.fd, name, maximum)
    if (_stable(before) != _stable(os.stat(name, dir_fd=chain.fd, follow_symlinks=False))
            or _read_at(chain.fd, name, maximum) != raw):
        _fail()
    chain.check()
    return raw


def _expected_native_record(
    parsed_anchor: dict, lookup: dict, value: dict, key: WorkerOriginKey,
    mapping: WorkerNativeTaskMapping,
) -> bytes:
    # Exact unchanged V1 payload, derived from original anchor/assignment; current
    # metadata is never promoted to an original native creator pin.
    unsigned = {"protocol": native_vault._PROTOCOL, "kind": "original-anchor-custody",
                "profile_sha256": value["profile_sha256"], "lookup": lookup,
                "context": lookup["context"], "mapping": mapping.to_dict(),
                "anchor": parsed_anchor, "production_admission": False,
                **{name: value[name] for name in _IDENTITY}}
    mac = hmac.new(key.secret_key, native_vault._DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
    return worker_json({**unsigned, "mac_sha256": mac})


def _original_packet(anchor: dict) -> NativeTrustedRegisteredContext:
    chain = DirectoryChain(_path(anchor["worker_path"]), "worker_guardian_vault_worker_drift")
    try:
        _verify_chain(chain, anchor["worker_chain"])
        native_vault._private_chain(chain)
        packet = parse_worker_json(
            _bound(chain, "native-restart-packet.json", _file_pin(anchor["packet_identity"])),
            2 * 1024 * 1024,
        )
        complete = parse_worker_json(
            _bound(chain, "native-restart-complete.json", _file_pin(anchor["complete_identity"])),
            2 * 1024 * 1024,
        )
        if complete.get("packet_identity") != anchor["packet_identity"]:
            _fail()
        native = _restore_native(packet["native"])
        _verify_chain(chain, anchor["worker_chain"])
        native_vault._private_chain(chain)
        return native
    finally:
        chain.close()


def _reference(
    reference: GuardianNativeRegistrationReference, context: WorkerOriginContext,
    profile: str, native: NativeTrustedRegisteredContext, *, before_gate: bool,
) -> tuple[dict, dict]:
    if type(reference) is not GuardianNativeRegistrationReference:
        _fail()
    original = reference.canonical_bytes
    value = _guardian_parse(original, 32768)
    if _guardian_json(value) != original:
        _fail()
    receiver = value["receiver_reference"]
    expected_context = hashlib.sha256(worker_json(context.to_dict())).hexdigest()
    if (receiver["context_sha256"] != expected_context or receiver["profile_sha256"] != profile
            or value["native_binding"]["native"] != _native_projection(native)):
        _fail()
    report = inspect_registered_native_guardian_custody(reference)
    allowed = {"registered"} if before_gate else {"registered", "watcher_exit_observed"}
    if report["state"] not in allowed or report["native_registration_binding_observed"] is not True:
        _fail()
    if reference.canonical_bytes != original:
        _fail()
    return value, report


def _create(
    chain: DirectoryChain, name: str, raw: bytes, checkpoint: Callable[[], None],
) -> tuple[str | int, ...]:
    """Create-only pending/link publication with per-action original checks.

    Partial pending/final entries remain. The actual creator FD stays open
    through directory fsync and readback. Blocking fsync still has no hard bound.
    """
    checkpoint()
    fd = os.open(name + ".pending", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=chain.fd)
    try:
        checkpoint()
        created = os.fstat(fd)
        offset = 0
        while offset < len(raw):
            checkpoint()
            count = os.write(fd, raw[offset:])
            if count <= 0:
                _fail()
            offset += count
            checkpoint()
        checkpoint()
        os.fsync(fd)
        checkpoint()
        written = os.fstat(fd)
        if (not stat.S_ISREG(written.st_mode) or written.st_nlink != 1
                or written.st_uid != os.geteuid() or stat.S_IMODE(written.st_mode) != 0o600
                or written.st_size != len(raw)
                or (written.st_dev, written.st_ino) != (created.st_dev, created.st_ino)):
            _fail()
        checkpoint()
        os.link(name + ".pending", name, src_dir_fd=chain.fd, dst_dir_fd=chain.fd,
                follow_symlinks=False)
        checkpoint()
        os.unlink(name + ".pending", dir_fd=chain.fd)
        checkpoint()
        os.fsync(chain.fd)
        checkpoint()
        published = os.fstat(fd)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (_stable(published) != _stable(named) or published.st_nlink != 1
                or (published.st_dev, published.st_ino, published.st_size, published.st_mtime_ns)
                != (written.st_dev, written.st_ino, written.st_size, written.st_mtime_ns)
                or published.st_mode != written.st_mode or published.st_uid != written.st_uid):
            _fail()
        pin = _file_pin((hashlib.sha256(raw).hexdigest(), published.st_size,
                         published.st_dev, published.st_ino,
                         published.st_mtime_ns, published.st_ctime_ns))
        checkpoint()
        if _bound(chain, name, pin) != raw:
            _fail()
        checkpoint()
        if _stable(os.fstat(fd)) != _stable(published):
            _fail()
        return pin
    finally:
        os.close(fd)


def retain_installed_guardian_reference(
    installation: native_vault.InstalledWorkerNativeVault,
    reference: GuardianNativeRegistrationReference, native_anchor: WorkerNativeRestartAnchor,
    raw: bytes, *, native_context: NativeTrustedRegisteredContext, key: WorkerOriginKey,
    expected_context: WorkerOriginContext, expected_mapping: WorkerNativeTaskMapping,
    expected_profile_sha256: str, check: Callable[[], None],
) -> None:
    """Original observer only; old native anchor must already be independently durable."""
    chain = None
    try:
        if not callable(check):
            _fail()
        deadline = parse_worker_json(native_context.deadline_json, 32768)["deadline_monotonic"]
        if type(deadline) not in {int, float} or not math.isfinite(deadline):
            _fail()

        def checkpoint() -> None:
            if time.monotonic() >= deadline or check() is not None or time.monotonic() >= deadline:
                _fail()

        checkpoint()
        lookup = native_vault._originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = native_vault._open(installation, key, expected_profile_sha256)
        installation_bytes, reference_bytes, anchor_bytes = (
            installation.canonical_bytes, reference.canonical_bytes, native_anchor.canonical_bytes,
        )
        assignment = worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()})
        anchor = native_vault._anchor(native_anchor, value, lookup)
        packet_native = _original_packet(anchor)
        if _native_wire(packet_native) != _native_wire(native_context):
            _fail()
        guardian, _ = _reference(reference, expected_context, expected_profile_sha256,
                                 native_context, before_gate=True)
        native_vault.check_installed_vault_separation(
            installation, key=key, profile_sha256=expected_profile_sha256,
            private_roots=(_path(guardian["directory"]),),
        )
        expected_native = _expected_native_record(anchor, lookup, value, key, expected_mapping)
        native_name = hashlib.sha256(raw).hexdigest() + ".json"
        if _read_stable(chain, native_name, native_vault._MAX) != expected_native:
            _fail()
        checkpoint()
        unsigned = {"protocol": _PROTOCOL, "kind": "original-guardian-reference-custody",
                    "profile_sha256": expected_profile_sha256, "lookup": lookup,
                    "context": expected_context.to_dict(), "mapping": expected_mapping.to_dict(),
                    "native_anchor": anchor, "guardian_reference": guardian,
                    "native_vault_sha256": hashlib.sha256(expected_native).hexdigest(),
                    **{name: value[name] for name in _IDENTITY}, **_FALSE}
        mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        record = worker_json({**unsigned, "mac_sha256": mac})
        if len(record) > _MAX:
            _fail()
        pin = _create(chain, _name(raw), record, checkpoint)
        if _bound(chain, _name(raw), pin) != record:
            _fail()
        checkpoint()
        _reference(reference, expected_context, expected_profile_sha256, native_context, before_gate=True)
        if (_read_stable(chain, native_name, native_vault._MAX) != expected_native
                or installation.canonical_bytes != installation_bytes
                or reference.canonical_bytes != reference_bytes or native_anchor.canonical_bytes != anchor_bytes
                or worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}) != assignment
                or native_vault._installation(installation, key, expected_profile_sha256) != value):
            _fail()
        _verify_chain(chain, value["directory_chain"])
        native_vault._private_chain(chain)
        checkpoint()
    except Exception:  # noqa: BLE001 - the explicit pre-gate custody boundary always fails closed
        raise WorkerGuardianVaultError("worker_guardian_vault_custody_refused") from None
    finally:
        if chain is not None:
            chain.close()


def inspect_installed_guardian_reference(
    raw: bytes, *, installation: native_vault.InstalledWorkerNativeVault | None,
    key: WorkerOriginKey, expected_context: WorkerOriginContext,
    expected_mapping: WorkerNativeTaskMapping, expected_profile_sha256: str,
) -> dict:
    """Fixed original installation lookup; no launch, repair, signal or renewed budget."""
    unavailable = {"protocol": _PROTOCOL, "status": "context_unavailable",
                   "execution_status": "unknown",
                   "guardian_reference_custody_observed": False,
                   "native_registration_binding_observed": False,
                   "cleanup_status": "unknown", "signal_result_known": False, **_FALSE}
    chain = None
    try:
        lookup = native_vault._originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = native_vault._open(installation, key, expected_profile_sha256)
        baseline = installation.canonical_bytes
        assignment = worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()})
        record = _read_stable(chain, _name(raw), _MAX)
        parsed = _object(parse_worker_json(record, _MAX), _FIELDS | {"mac_sha256"})
        unsigned = {name: item for name, item in parsed.items() if name != "mac_sha256"}
        expected_mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        if (not hmac.compare_digest(_digest(parsed["mac_sha256"]), expected_mac)
                or parsed["protocol"] != _PROTOCOL or parsed["kind"] != "original-guardian-reference-custody"
                or parsed["lookup"] != lookup or parsed["context"] != expected_context.to_dict()
                or parsed["mapping"] != expected_mapping.to_dict()
                or parsed["profile_sha256"] != expected_profile_sha256
                or any(parsed[name] != value[name] for name in _IDENTITY)
                or any(parsed[name] is not False for name in _FALSE)):
            _fail()
        anchor = WorkerNativeRestartAnchor(worker_json(parsed["native_anchor"]))
        original_anchor = native_vault._anchor(anchor, value, lookup)
        native = _original_packet(original_anchor)
        reference = GuardianNativeRegistrationReference(_guardian_json(parsed["guardian_reference"]))
        guardian, report = _reference(reference, expected_context, expected_profile_sha256,
                                      native, before_gate=False)
        native_vault.check_installed_vault_separation(
            installation, key=key, profile_sha256=expected_profile_sha256,
            private_roots=(_path(guardian["directory"]),),
        )
        expected_native = _expected_native_record(original_anchor, lookup, value, key, expected_mapping)
        native_name = hashlib.sha256(raw).hexdigest() + ".json"
        if (hashlib.sha256(expected_native).hexdigest() != _digest(parsed["native_vault_sha256"])
                or _read_stable(chain, native_name, native_vault._MAX) != expected_native):
            _fail()
        native_report = native_vault.inspect_installed_native_restart(
            raw, installation=installation, key=key, expected_context=expected_context,
            expected_mapping=expected_mapping, expected_profile_sha256=expected_profile_sha256,
        )
        if native_report["independent_anchor_custody_observed"] is not True:
            _fail()
        if _reference(reference, expected_context, expected_profile_sha256,
                      native, before_gate=False)[1] != report:
            _fail()
        if (_read_stable(chain, _name(raw), _MAX) != record
                or _read_stable(chain, native_name, native_vault._MAX) != expected_native
                or installation.canonical_bytes != baseline
                or worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}) != assignment
                or native_vault._installation(installation, key, expected_profile_sha256) != value):
            _fail()
        _verify_chain(chain, value["directory_chain"])
        native_vault._private_chain(chain)
        return {**report, "protocol": _PROTOCOL, "status": "custody_observed",
                "execution_status": "unknown",
                "guardian_reference_custody_observed": True, "native": native_report, **_FALSE}
    except Exception:  # noqa: BLE001 - missing, partial and drifted original custody remain unavailable
        return unavailable
    finally:
        if chain is not None:
            chain.close()
