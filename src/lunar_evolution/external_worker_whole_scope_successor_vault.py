"""Independent pre-gate custody of original v4 successor references.

Only the original live scope supplies creator-backed data to the writer. A
restart lookup consumes that independently retained data read-only; it never
recreates an owner, proves an ACK or grants execution/cleanup authority.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable

from . import external_worker_guardian_vault as shared
from . import external_worker_native_vault as native_vault
from .external_worker_native_lifecycle import WorkerNativeTaskMapping
from .external_worker_native_restart import (
    WorkerNativeRestartAnchor,
    _bound,
    _digest,
    _native_wire,
    _object,
    _path,
    _verify_chain,
)
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey
from .external_worker_wrapper import parse_worker_json, worker_json
from .native_deadline_binding import (
    validate_native_deadline_binding,
    verify_native_deadline_record_binding,
)
from .native_trusted_attempt import NativeTrustedRegisteredContext
from .native_whole_scope import _BINDING, _HEADER, _PUBLICATION, NativeWholeScopeOwner
from .native_whole_scope_custody import _json
from .native_whole_scope_successor import (
    CONTEXT_SIZE,
    PROFILE_NAME,
    _SuccessorSession,
)
from .native_whole_scope_successor import (
    context as _successor_context,
)
from .native_whole_scope_successor_custody import (
    NativeWholeScopeSuccessorCustodyOwner,
    NativeWholeScopeSuccessorCustodyReference,
    _parse_reference,
    inspect_native_whole_scope_successor_custody,
)

_PROTOCOL = "lunar-installed-worker-whole-scope-successor-v4-vault-v1"
_DOMAIN = b"lunar-installed-worker-whole-scope-successor-v4-vault-v1\0"
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_MAX = 256 * 1024
_FALSE = dict.fromkeys(("production_admission", "native_success", "publication_authority",
                        "cleanup_authority", "online_publication"), False)
_FIELDS = {"protocol", "kind", "profile_sha256", "whole_scope_profile_sha256", "lookup",
           "context", "mapping", "native_anchor", "native_vault_sha256", "native_binding_sha256",
           "native_deadline_ns", "whole_scope_reference", *_IDENTITY, *_FALSE}


class WorkerWholeScopeSuccessorVaultError(ValueError):
    """A fixed refusal without original authorization, paths or key material."""


def _fail() -> None:
    raise WorkerWholeScopeSuccessorVaultError("worker_whole_scope_successor_vault_custody_refused")


def _name(raw: bytes) -> str:
    return "whole-scope-successor-v4-" + hashlib.sha256(raw).hexdigest() + ".json"


def _publications(native: NativeTrustedRegisteredContext) -> tuple[tuple, ...]:
    """Derive the third *comparison* pin from the original deadline binding.

    The writer separately matches these with its three retained original OFDs.
    This detached projection can neither create an OFD nor establish its origin.
    """
    if type(native) is not NativeTrustedRegisteredContext or native.publication_eligible is not False:
        _fail()
    binding = validate_native_deadline_binding(parse_worker_json(native.deadline_binding_json, 4096))
    verify_native_deadline_record_binding(parse_worker_json(native.deadline_json, 16384), binding)
    pins = (native.registration_file_identity, native.handoff_file_identity,
            (binding["raw_sha256"], binding["size"], binding["device"], binding["inode"],
             binding["mtime_ns"], binding["ctime_ns"]))
    for pin, raw in zip(pins, (native.registration_json, native.handoff_json, native.deadline_json), strict=True):
        native_vault._file_pin(pin)
        if pin[0] != hashlib.sha256(raw).hexdigest() or pin[1] != len(raw):
            _fail()
    return pins


def _reference(reference, native, profile, deadline_ns, *, before_gate):
    value, registration = _parse_reference(reference)
    if value["profile"] != PROFILE_NAME:
        _fail()
    binding = _BINDING.unpack_from(registration, _HEADER.size)
    process = parse_worker_json(native.registration_json, 65536)
    # The target PID in the scope is T, whereas native registration names B.
    # Compare the original target image binding, never equate these two PIDs.
    if (type(deadline_ns) is not int or binding[0] != deadline_ns
            or binding[1] != _digest(native.launch_sha256).encode() + b"\0"
            or binding[2] != _digest(native.intent_sha256).encode() + b"\0"
            or binding[3] != _digest(process.get("target_execution_snapshot_sha256")).encode() + b"\0"
            or binding[4] != _digest(native.bootstrap_artifact_sha256).encode() + b"\0"
            or binding[6] != _digest(profile).encode() + b"\0"):
        _fail()
    pins = _publications(native)
    expected = b"".join(_PUBLICATION.pack(dev, ino, size, mtime, ctime, digest.encode() + b"\0")
                        for digest, size, dev, ino, mtime, ctime in pins)
    if registration[-3 * _PUBLICATION.size:] != expected:
        _fail()
    report = inspect_native_whole_scope_successor_custody(reference)
    allowed = {"registration_prefix_observed"} if before_gate else {
        "registration_prefix_observed", "terminal_record_observed", "abnormal_record_observed",
    }
    if report["state"] not in allowed or report["registration_record_observed"] is not True:
        _fail()
    return value, report


def _live(scope, native, profile):
    if (type(scope) is not NativeWholeScopeOwner or scope._closed or not scope._registered
            or scope._released or scope._finished or scope._profile_sha256 != _digest(profile)):
        _fail()
    session = scope._successor_session
    if type(session) is not _SuccessorSession or session.owner is not scope:
        _fail()
    session.check()
    scope._remaining()
    scope._check_published_grants()
    child = scope.original_custody_owner
    if (type(child) is not NativeWholeScopeSuccessorCustodyOwner or child.profile != PROFILE_NAME
            or child._scope is not scope or child._session is not session):
        _fail()
    child._check_registration()
    reference = child.reference
    value, _report = _reference(reference, native, profile, scope.deadline_ns, before_gate=True)
    registration = bytes.fromhex(value["registration"])
    publications = scope._original_publications._borrow_for_native_transfer()[1]
    raw = b"".join(_PUBLICATION.pack(dev, ino, size, mtime, ctime, digest.encode() + b"\0")
                   for digest, size, dev, ino, mtime, ctime in publications)
    expected = _successor_context(scope._binding, scope._scope, scope._target_pid, raw, 79, 1)
    if (len(registration) != CONTEXT_SIZE or registration != expected
            or session.registration != expected or publications != _publications(native)):
        _fail()
    scope._remaining()
    return reference


def retain_installed_whole_scope_successor_reference(
    installation: native_vault.InstalledWorkerNativeVault,
    scope: NativeWholeScopeOwner, native_anchor: WorkerNativeRestartAnchor, raw: bytes, *,
    native_context: NativeTrustedRegisteredContext, key: WorkerOriginKey,
    expected_context: WorkerOriginContext, expected_mapping: WorkerNativeTaskMapping,
    expected_profile_sha256: str, expected_whole_scope_profile_sha256: str,
    check: Callable[[], None],
) -> None:
    """The original registered observer writes once, before either release gate.

    Storage syscalls can block. Checks refuse late return; this writer owns no
    scope/pidfd/lifeline endpoint and does not defer independent native stopping.
    Partial files remain and a failed attempt is never retried or repaired.
    """
    chain = None
    try:
        if not callable(check):
            _fail()
        scope_profile = _digest(expected_whole_scope_profile_sha256)
        original_session, original_child = scope._successor_session, scope._custody_owner
        reference = _live(scope, native_context, scope_profile)
        if (scope._successor_session is not original_session
                or scope._custody_owner is not original_child):
            _fail()
        baseline = (installation.canonical_bytes, reference.canonical_bytes, native_anchor.canonical_bytes,
                    worker_json(_native_wire(native_context)),
                    worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}),
                    tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key), scope.deadline_ns)

        def checkpoint():
            if check() is not None or time.monotonic_ns() >= baseline[7]:
                _fail()
            if (scope._successor_session is not original_session
                    or scope._custody_owner is not original_child):
                _fail()
            current = _live(scope, native_context, scope_profile)
            if (scope._successor_session is not original_session
                    or scope._custody_owner is not original_child
                    or current is not reference
                    or (installation.canonical_bytes, current.canonical_bytes, native_anchor.canonical_bytes,
                 worker_json(_native_wire(native_context)),
                 worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}),
                 tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key), scope.deadline_ns)
                    != baseline):
                _fail()

        checkpoint()
        lookup = native_vault._originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = native_vault._open(installation, key, expected_profile_sha256)
        anchor = native_vault._anchor(native_anchor, value, lookup)
        if _native_wire(shared._original_packet(anchor)) != _native_wire(native_context):
            _fail()
        parsed, _ = _parse_reference(reference)
        native_vault.check_installed_vault_separation(
            installation, key=key, profile_sha256=expected_profile_sha256,
            private_roots=tuple(_path(path) for path in (*scope._profile["paths"], parsed["path"],
                                                        native_context.workspace, native_context.producer_root,
                                                        str(_path(native_context.artifact_path).parent),
                                                        anchor["worker_path"])),
        )
        expected_native = shared._expected_native_record(anchor, lookup, value, key, expected_mapping)
        native_name = hashlib.sha256(raw).hexdigest() + ".json"
        if shared._read_stable(chain, native_name, native_vault._MAX) != expected_native:
            _fail()
        checkpoint()
        unsigned = {"protocol": _PROTOCOL, "kind": "original-whole-scope-successor-reference-custody",
                    "profile_sha256": expected_profile_sha256, "whole_scope_profile_sha256": scope_profile,
                    "lookup": lookup, "context": expected_context.to_dict(), "mapping": expected_mapping.to_dict(),
                    "native_anchor": anchor, "whole_scope_reference": parsed,
                    "native_vault_sha256": hashlib.sha256(expected_native).hexdigest(),
                    "native_binding_sha256": hashlib.sha256(baseline[3]).hexdigest(),
                    "native_deadline_ns": baseline[7], **{name: value[name] for name in _IDENTITY}, **_FALSE}
        mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        record = worker_json({**unsigned, "mac_sha256": mac})
        if len(record) > _MAX:
            _fail()
        pin = shared._create(chain, _name(raw), record, checkpoint)
        if (_bound(chain, _name(raw), pin) != record
                or shared._read_stable(chain, native_name, native_vault._MAX) != expected_native):
            _fail()
        checkpoint()
        _verify_chain(chain, value["directory_chain"])
        native_vault._private_chain(chain)
        if native_vault._installation(installation, key, expected_profile_sha256) != value:
            _fail()
        checkpoint()
        # The in-memory original packet cannot stand in for its independently
        # retained files after storage work. Refuse observed packet/complete
        # drift before this observer can return to either execution gate.
        if _native_wire(shared._original_packet(anchor)) != _native_wire(native_context):
            _fail()
        checkpoint()
    except Exception:  # noqa: BLE001 - pre-gate errors expose no installed/private data
        raise WorkerWholeScopeSuccessorVaultError("worker_whole_scope_successor_vault_custody_refused") from None
    finally:
        if chain is not None:
            chain.close()


def inspect_installed_whole_scope_successor_reference(
    raw: bytes, *, installation: native_vault.InstalledWorkerNativeVault | None,
    key: WorkerOriginKey, expected_context: WorkerOriginContext,
    expected_mapping: WorkerNativeTaskMapping, expected_profile_sha256: str,
    expected_whole_scope_profile_sha256: str,
) -> dict:
    """Read one authenticated original sidecar, without process or write actions."""
    unavailable = {"protocol": _PROTOCOL, "status": "context_unavailable", "execution_status": "unknown",
                   "whole_scope_reference_custody_observed": False, "cleanup_status": "unknown",
                   "whole_group_cleanup_verified": False, "durable_acknowledgement_verified": False,
                   "original_quiescence_observed": False, **_FALSE}
    chain = None
    try:
        scope_profile = _digest(expected_whole_scope_profile_sha256)
        lookup = native_vault._originals(raw, expected_context, expected_mapping, expected_profile_sha256)
        value, chain = native_vault._open(installation, key, expected_profile_sha256)
        baseline = (installation.canonical_bytes,
                    worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}),
                    tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key))
        record = shared._read_stable(chain, _name(raw), _MAX)
        parsed = _object(parse_worker_json(record, _MAX), _FIELDS | {"mac_sha256"})
        unsigned = {name: item for name, item in parsed.items() if name != "mac_sha256"}
        mac = hmac.new(key.secret_key, _DOMAIN + worker_json(unsigned), hashlib.sha256).hexdigest()
        if (not hmac.compare_digest(_digest(parsed["mac_sha256"]), mac)
                or parsed["protocol"] != _PROTOCOL or parsed["kind"] != "original-whole-scope-successor-reference-custody"
                or parsed["lookup"] != lookup or parsed["context"] != expected_context.to_dict()
                or parsed["mapping"] != expected_mapping.to_dict()
                or parsed["profile_sha256"] != expected_profile_sha256
                or parsed["whole_scope_profile_sha256"] != scope_profile
                or any(parsed[name] != value[name] for name in _IDENTITY)
                or any(parsed[name] is not False for name in _FALSE)):
            _fail()
        anchor = native_vault._anchor(WorkerNativeRestartAnchor(worker_json(parsed["native_anchor"])), value, lookup)
        native = shared._original_packet(anchor)
        if hashlib.sha256(worker_json(_native_wire(native))).hexdigest() != _digest(parsed["native_binding_sha256"]):
            _fail()
        reference = NativeWholeScopeSuccessorCustodyReference(_json(parsed["whole_scope_reference"]))
        custody, report = _reference(reference, native, scope_profile, parsed["native_deadline_ns"], before_gate=False)
        native_vault.check_installed_vault_separation(
            installation, key=key, profile_sha256=expected_profile_sha256,
            private_roots=(_path(custody["path"]), _path(native.workspace), _path(native.producer_root),
                           _path(native.artifact_path).parent, _path(anchor["worker_path"])),
        )
        expected_native = shared._expected_native_record(anchor, lookup, value, key, expected_mapping)
        native_name = hashlib.sha256(raw).hexdigest() + ".json"
        if (hashlib.sha256(expected_native).hexdigest() != _digest(parsed["native_vault_sha256"])
                or shared._read_stable(chain, native_name, native_vault._MAX) != expected_native):
            _fail()
        native_report = native_vault.inspect_installed_native_restart(
            raw, installation=installation, key=key, expected_context=expected_context,
            expected_mapping=expected_mapping, expected_profile_sha256=expected_profile_sha256,
        )
        if native_report["independent_anchor_custody_observed"] is not True:
            _fail()
        if _reference(reference, native, scope_profile, parsed["native_deadline_ns"], before_gate=False)[1] != report:
            _fail()
        if (shared._read_stable(chain, _name(raw), _MAX) != record
                or shared._read_stable(chain, native_name, native_vault._MAX) != expected_native
                or (installation.canonical_bytes,
                    worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}),
                    tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key)) != baseline
                or native_vault._installation(installation, key, expected_profile_sha256) != value):
            _fail()
        _verify_chain(chain, value["directory_chain"])
        native_vault._private_chain(chain)
        if ((installation.canonical_bytes,
             worker_json({"context": expected_context.to_dict(), "mapping": expected_mapping.to_dict()}),
             tuple(getattr(key, name) for name in _IDENTITY), bytes(key.secret_key)) != baseline
                or native_vault._installation(installation, key, expected_profile_sha256) != value):
            _fail()
        return {**report, "protocol": _PROTOCOL, "status": "custody_observed", "execution_status": "unknown",
                "whole_scope_reference_custody_observed": True, "native": native_report, **_FALSE}
    except Exception:  # noqa: BLE001 - a missing original never creates a replacement reference
        return unavailable
    finally:
        if chain is not None:
            chain.close()
