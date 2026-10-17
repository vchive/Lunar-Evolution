"""Read-only, entry-bound native producer process observations for BRS recovery.

The native producer is an OS process, not the BRS publication thread. These
values grant no cleanup, publication, result or reconcile-consumption authority.
File pins describe this capture entry, never historical creator inode provenance.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import canonical_json
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import recover_native_trusted_attempt
from .native_trusted_cleanup import verify_native_trusted_cleanup
from .native_trusted_receipt import recover_native_trusted_execution_receipt
from .producer_bootstrap import (
    build_trusted_bootstrap_launch,
    verify_trusted_bootstrap_process_registration,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import _process_owner_identity
from .rsi_native_plan import NativeRSIExecutionPlan

PROTOCOL = "lunar-rsi-brs-native-process-binding-v1"
ROLE = "native-producer-process"
_MAX = 128 * 1024
_MAX_FILE = 256 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_NAMES = (
    "process-registration.json", "execution-receipt.json",
    "native-trusted-process-terminal.json", "native-trusted-cleanup.json",
)
_FIELDS = frozenset({
    "protocol", "role", "status", "reason", "native_plan_sha256", "request_sha256",
    "workspace", "references", "entries", "binding_sha256",
})
_REF_FIELDS = frozenset({
    "launch_id", "journal_id", "intent_sha256", "attestation_sha256",
    "registration_sha256", "execution_receipt_sha256", "process_terminal_sha256",
    "cleanup_sha256", "deadline_sha256", "pid", "pgid", "owner_identity",
    "owner_identity_sha256",
})
_PIN_FIELDS = frozenset({
    "name", "device", "inode", "parent_device", "parent_inode", "size",
    "mtime_ns", "ctime_ns", "sha256",
})
_REASONS = frozenset({
    "native_records_captured", "native_context_unavailable", "native_records_unavailable",
    "native_records_invalid", "native_workspace_unavailable",
})


class BRSNativeProcessEvidenceError(ValueError):
    """Fixed local evidence errors; never expose producer prose or OS paths."""


def _fail(reason: str) -> None:
    raise BRSNativeProcessEvidenceError("rsi_brs_native_process_" + reason)


def _plain(value: object, depth: int = 0, remaining: list[int] | None = None):
    if remaining is None:
        remaining = [4096]
    remaining[0] -= 1
    if depth > 16 or remaining[0] < 0:
        _fail("wire_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 128:
        return value
    if kind is str and len(value) <= _MAX:
        return value
    if kind is dict and all(type(key) is str for key in value):
        return {key: _plain(item, depth + 1, remaining) for key, item in value.items()}
    _fail("wire_invalid")


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _number(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        _fail("identity_invalid")
    return value


def _digest(value: dict, field: str) -> str:
    return hashlib.sha256(canonical_json(
        {key: item for key, item in value.items() if key != field}, maximum=_MAX,
    )).hexdigest()


def _owner(value: object, pid: int) -> dict:
    if type(value) is not dict or value.get("pid") != pid:
        _fail("owner_identity_invalid")
    if value.get("kind") == "linux-proc-starttime-v1":
        if (set(value) != {"kind", "pid", "boot_id", "starttime_ticks"}
                or type(value["boot_id"]) is not str or not 1 <= len(value["boot_id"]) <= 128):
            _fail("owner_identity_invalid")
        _number(value["starttime_ticks"], 1)
    elif value.get("kind") == "darwin-libproc-starttime-v1":
        if set(value) != {"kind", "pid", "start_sec", "start_usec"}:
            _fail("owner_identity_invalid")
        _number(value["start_sec"], 1)
        if _number(value["start_usec"]) >= 1_000_000:
            _fail("owner_identity_invalid")
    else:
        _fail("owner_identity_invalid")
    _number(value["pid"], 2)
    return value


def parse_native_process_binding(value: object) -> dict:
    """Validate and detach one bounded capture; this performs no file/OS reads."""
    clean = _plain(value)
    if (type(clean) is not dict or set(clean) != _FIELDS
            or any(type(clean[key]) is not str for key in ("protocol", "role", "status", "reason"))
            or clean["protocol"] != PROTOCOL or clean["role"] != ROLE
            or clean["status"] not in {"captured", "unknown"}
            or clean["reason"] not in _REASONS):
        _fail("binding_invalid")
    for key in ("native_plan_sha256", "request_sha256", "binding_sha256"):
        _sha(clean[key])
    workspace = clean["workspace"]
    if workspace is not None:
        if (type(workspace) is not dict or set(workspace) != {"path", "device", "inode"}
                or type(workspace["path"]) is not str or not workspace["path"]
                or "\x00" in workspace["path"] or not Path(workspace["path"]).is_absolute()
                or ".." in Path(workspace["path"]).parts):
            _fail("workspace_invalid")
        _number(workspace["device"])
        _number(workspace["inode"], 1)
    if clean["status"] == "unknown":
        if (clean["references"] is not None or clean["entries"] != {}
                or clean["reason"] == "native_records_captured"):
            _fail("binding_invalid")
    else:
        refs, entries = clean["references"], clean["entries"]
        if (workspace is None or clean["reason"] != "native_records_captured"
                or type(refs) is not dict or set(refs) != _REF_FIELDS
                or type(entries) is not dict or set(entries) != set(_NAMES)):
            _fail("binding_invalid")
        for key in ("launch_id", "journal_id"):
            if type(refs[key]) is not str or _ID.fullmatch(refs[key]) is None:
                _fail("binding_invalid")
        for key in _REF_FIELDS - {"launch_id", "journal_id", "pid", "pgid", "owner_identity"}:
            _sha(refs[key])
        pid = _number(refs["pid"], 2)
        if _number(refs["pgid"], 2) != pid:
            _fail("identity_invalid")
        owner = _owner(refs["owner_identity"], pid)
        if hashlib.sha256(canonical_json(owner)).hexdigest() != refs["owner_identity_sha256"]:
            _fail("owner_identity_invalid")
        for name in _NAMES:
            pin = entries[name]
            if type(pin) is not dict or set(pin) != _PIN_FIELDS or pin["name"] != name:
                _fail("entry_invalid")
            _sha(pin["sha256"])
            for key in _PIN_FIELDS - {"name", "sha256"}:
                _number(pin[key], 1 if key in {"inode", "parent_inode"} else 0)
            if not 0 < pin["size"] <= _MAX_FILE:
                _fail("entry_invalid")
    if _digest(clean, "binding_sha256") != clean["binding_sha256"]:
        _fail("binding_digest_mismatch")
    return clean


def _workspace(workspace: Path) -> dict:
    if type(workspace) is not type(Path()):
        _fail("workspace_invalid")
    path = workspace.absolute()
    if ".." in path.parts:
        _fail("workspace_invalid")
    chain = DirectoryChain(path, "rsi_brs_native_process_workspace_invalid")
    try:
        info = os.fstat(chain.fd)
        chain.check()
        return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}
    finally:
        chain.close()


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, item in pairs:
        if key in result:
            _fail("entry_invalid")
        result[key] = item
    return result


def _entry(batch: Path, name: str) -> tuple[dict, dict]:
    """Read an original fixed name through held directories without following links."""
    chain = DirectoryChain(batch, "rsi_brs_native_process_entry_invalid")
    try:
        before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= _MAX_FILE):
            _fail("entry_invalid")
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=chain.fd)
        try:
            opened = os.fstat(descriptor)
            data = bytearray()
            while len(data) <= _MAX_FILE:
                chunk = os.read(descriptor, min(64 * 1024, _MAX_FILE + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        current = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (len(data) > _MAX_FILE or any(_identity(info) != _identity(before)
                                       for info in (opened, after, current))):
            _fail("entry_changed")
        chain.check()
        parent = os.fstat(chain.fd)
        raw = json.loads(data, object_pairs_hook=_pairs)
        if type(raw) is not dict or canonical_json(raw, maximum=_MAX_FILE) != data:
            _fail("entry_invalid")
        return ({"name": name, "device": before.st_dev, "inode": before.st_ino,
                 "parent_device": parent.st_dev, "parent_inode": parent.st_ino,
                 "size": before.st_size, "mtime_ns": before.st_mtime_ns,
                 "ctime_ns": before.st_ctime_ns, "sha256": hashlib.sha256(data).hexdigest()}, raw)
    finally:
        chain.close()


def _records(workspace: Path, plan: NativeRSIExecutionPlan, intent: ProducerLaunchIntent,
             attestation: ProducerLaunchAttestation, artifact: NativeBootstrapArtifact) -> tuple[dict, dict]:
    if (type(intent) is not ProducerLaunchIntent or type(attestation) is not ProducerLaunchAttestation
            or type(artifact) is not NativeBootstrapArtifact):
        _fail("context_unavailable")
    if (any(getattr(plan, key) != getattr(intent, key) for key in (
            "run_id", "parent_task_id", "task_id", "launch_id", "journal_id", "intent_sha256"))
            or plan.attestation_sha256 != attestation.attestation_sha256
            or plan.bootstrap_descriptor_sha256 != artifact.descriptor.digest()
            or plan.bootstrap_artifact_sha256 != artifact.artifact_sha256):
        _fail("context_drift")
    batch = workspace / "evolution/producer-batches" / plan.journal_id
    first = {name: _entry(batch, name) for name in _NAMES}
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    registration = verify_trusted_bootstrap_process_registration(
        launch, artifact.descriptor, first[_NAMES[0]][1],
    )
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=False,
    )
    receipt = recover_native_trusted_execution_receipt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, require_broker=True,
    )
    cleanup = verify_native_trusted_cleanup(first[_NAMES[3]][1], intent=intent, terminal=terminal)
    if (first[_NAMES[1]][1] != receipt.to_dict() or first[_NAMES[2]][1] != terminal
            or receipt.registration_sha256 != registration["registration_sha256"]
            or receipt.pid != registration["pid"] or receipt.pgid != registration["pgid"]
            or receipt.owner_identity != registration["owner_identity"]
            or receipt.cleanup_sha256 != cleanup["cleanup_sha256"]
            or receipt.cleanup_status not in {"cleaned", "already_exited"}
            or type(receipt.trusted_execution) is not dict
            or receipt.trusted_execution.get("terminal_sha256") != terminal.get("terminal_sha256")):
        _fail("records_drift")
    repeated = {name: _entry(batch, name) for name in _NAMES}
    if first != repeated:
        _fail("entry_changed")
    refs = {key: registration[key] for key in (
        "launch_id", "journal_id", "intent_sha256", "attestation_sha256",
        "registration_sha256", "pid", "pgid", "owner_identity", "owner_identity_sha256",
    )}
    refs.update(execution_receipt_sha256=receipt.receipt_sha256,
                process_terminal_sha256=terminal["terminal_sha256"],
                cleanup_sha256=cleanup["cleanup_sha256"], deadline_sha256=terminal["deadline_sha256"])
    return refs, {name: item[0] for name, item in first.items()}


def _plan(native_plan: NativeRSIExecutionPlan) -> NativeRSIExecutionPlan:
    if type(native_plan) is not NativeRSIExecutionPlan:
        _fail("plan_invalid")
    return NativeRSIExecutionPlan.from_dict(native_plan.to_dict())


def capture_native_process_binding(
    *, workspace: Path, native_plan: NativeRSIExecutionPlan,
    intent: ProducerLaunchIntent | None = None,
    attestation: ProducerLaunchAttestation | None = None,
    artifact: NativeBootstrapArtifact | None = None,
) -> dict:
    """Capture original native references once; absent/invalid records stay unknown.

    The caller supplies context copied under the genuine original owner. This helper
    grants no owner authority and never blocks private publication on missing records.
    """
    plan = _plan(native_plan)
    result = {"protocol": PROTOCOL, "role": ROLE, "status": "unknown",
              "reason": "native_context_unavailable", "native_plan_sha256": plan.plan_sha256,
              "request_sha256": plan.request_sha256, "workspace": None,
              "references": None, "entries": {}}
    try:
        result["workspace"] = _workspace(workspace)
    except (OSError, ValueError):
        result["reason"] = "native_workspace_unavailable"
    else:
        if intent is not None and attestation is not None and artifact is not None:
            try:
                refs, entries = _records(Path(result["workspace"]["path"]), plan, intent, attestation, artifact)
                if _workspace(workspace) != result["workspace"]:
                    _fail("workspace_changed")
            except FileNotFoundError:
                result["reason"] = "native_records_unavailable"
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
                result["reason"] = "native_records_invalid"
            else:
                result.update(status="captured", reason="native_records_captured", references=refs, entries=entries)
    result["binding_sha256"] = _digest(result, "binding_sha256")
    return parse_native_process_binding(result)


def _group(pgid: int) -> str:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "absent"
    except OSError as exc:
        return "absent" if exc.errno == errno.ESRCH else "unknown"
    return "present"


def _process(refs: dict) -> tuple[str, str, dict | None]:
    try:
        owner = _process_owner_identity(refs["pid"])
    except (OSError, ValueError):
        return "unknown", "unknown", None
    if owner is not None:
        if owner != refs["owner_identity"]:
            return "drifted", "unknown", owner
        try:
            pgid = os.getpgid(refs["pid"])
        except OSError:
            return "unknown", "unknown", owner
        if pgid != refs["pgid"]:
            return "drifted", "unknown", owner
        group = _group(pgid)
        return ("running" if group == "present" else "unknown"), group, owner
    try:
        os.kill(refs["pid"], 0)
    except ProcessLookupError:
        group = _group(refs["pgid"])
        return ("exited" if group == "absent" else "unknown"), group, None
    except OSError:
        return "unknown", "unknown", None
    return "unknown", "unknown", None


def observe_native_process_binding(
    binding: dict, *, workspace: Path, native_plan: NativeRSIExecutionPlan,
    intent: ProducerLaunchIntent | None = None,
    attestation: ProducerLaunchAttestation | None = None,
    artifact: NativeBootstrapArtifact | None = None,
) -> dict:
    """Recheck the original entry; never fill an unknown capture from current files."""
    captured = parse_native_process_binding(binding)
    result = {"protocol": PROTOCOL + ":observation", "role": ROLE,
              "binding_sha256": captured["binding_sha256"], "status": "unknown",
              "process_state": "unknown", "process_group": "unknown",
              "observed_owner_identity": None, "cleanup_confirmed": False,
              "reason": "original_capture_unknown"}
    try:
        plan = _plan(native_plan)
        if (plan.plan_sha256 != captured["native_plan_sha256"]
                or plan.request_sha256 != captured["request_sha256"]
                or type(workspace) is not type(Path())
                or (captured["workspace"] is not None
                    and str(workspace.absolute()) != captured["workspace"]["path"])):
            _fail("binding_drift")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        result.update(status="drifted", reason="original_native_context_changed")
        result["observation_sha256"] = _digest(result, "observation_sha256")
        return _plain(result)
    if (captured["status"] == "captured"
            and (intent is None or attestation is None or artifact is None)):
        result["reason"] = "native_context_unavailable"
    elif captured["status"] == "captured":
        try:
            if _workspace(workspace) != captured["workspace"]:
                _fail("binding_drift")
            refs, entries = _records(Path(captured["workspace"]["path"]), plan, intent, attestation, artifact)
            if refs != captured["references"] or entries != captured["entries"]:
                _fail("binding_drift")
            status, group, owner = _process(refs)
            # An OS observation cannot hide a concurrent record/path replacement.
            if (_workspace(workspace) != captured["workspace"]
                    or any(_entry(Path(captured["workspace"]["path"]) / "evolution/producer-batches"
                                  / refs["journal_id"], name)[0] != entries[name] for name in _NAMES)):
                _fail("binding_drift")
            result.update(status=status, process_state=status if status in {"running", "exited"} else "unknown",
                          process_group=group, observed_owner_identity=owner,
                          cleanup_confirmed=status == "exited" and group == "absent",
                          reason="native_process_" + status)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            result.update(status="drifted", reason="original_native_binding_changed")
    result["observation_sha256"] = _digest(result, "observation_sha256")
    return _plain(result)


__all__ = [
    "BRSNativeProcessEvidenceError",
    "capture_native_process_binding",
    "observe_native_process_binding",
    "parse_native_process_binding",
]
