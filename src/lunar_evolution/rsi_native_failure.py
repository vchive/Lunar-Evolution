"""Immutable process-only native RSI failure evidence and create-only provenance.

Parsing this evidence does not prove filesystem provenance. The scheduler provider must reread
the native chain and the original ledger claim before the gateway may register its outcome.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import canonical_json, strict_json
from .native_trusted_failure import NativeTrustedProducerFailure
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_provenance import NATIVE_RSI_PROVENANCE_NAME
from .rsi_store import NativeEpisodeClaim, RSILedger

NATIVE_RSI_FAILURE_PROVENANCE_NAME = "native-rsi.failure-provenance.json"
# Native failure itself permits 2 MiB; leave bounded room for its complete plan and claim.
MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES = 3 * 1024 * 1024
_PROTOCOL = "lunar-native-rsi-failure-provenance-v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_PAYLOAD_FIELDS = {
    "schema_version", "protocol", "plan", "input_binding_sha256", "native_failure",
    "ledger_identity", "claim",
}
_IDENTITY_FIELDS = {"file_identity", "provenance_sha256"}
_CLAIM_FIELDS = {
    "episode_id", "request_sha256", "plan_sha256", "status", "claim_sha256", "created_at",
}


class NativeRSIFailureError(ValueError):
    """Fixed refusal codes, without producer prose or private filesystem details."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_native_failure_" + code
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise NativeRSIFailureError(code)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("invalid")
    return value


def _ledger_identity(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"database", "device", "inode"}:
        _fail("ledger_invalid")
    database = value["database"]
    if (type(database) is not str or not Path(database).is_absolute() or "\x00" in database
            or ".." in Path(database).parts or len(database.encode()) > 4096
            or database != str(Path(database).absolute())):
        _fail("ledger_invalid")
    if (type(value["device"]) is not int or value["device"] < 0
            or type(value["inode"]) is not int or value["inode"] <= 0):
        _fail("ledger_invalid")
    return {"database": database, "device": value["device"], "inode": value["inode"]}


def _assert_claim(claim: NativeEpisodeClaim, plan: NativeRSIExecutionPlan) -> None:
    if (not isinstance(claim, NativeEpisodeClaim) or claim.status != "started"
            or claim.episode_id != plan.request.episode_id
            or claim.request_sha256 != plan.request_sha256
            or claim.plan_sha256 != plan.plan_sha256
            or type(claim.created_at) is not str or not claim.created_at.strip()
            or len(claim.created_at.encode()) > 128):
        _fail("claim_mismatch")
    _sha(claim.claim_sha256)
    if claim.claim_sha256 != RSILedger._native_claim_digest(
        claim.episode_id, claim.request_sha256, claim.plan_sha256,
    ):
        _fail("claim_mismatch")


@dataclass(frozen=True, slots=True)
class NativeRSIFailureEvidence:
    """Separate failure proof; no candidate or successful execution receipt is manufactured."""

    plan: NativeRSIExecutionPlan
    failure: NativeTrustedProducerFailure
    input_binding_sha256: str
    ledger_identity: Mapping[str, Any]
    claim: NativeEpisodeClaim
    provenance_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, NativeRSIExecutionPlan):
            _fail("plan_invalid")
        if not isinstance(self.failure, NativeTrustedProducerFailure):
            _fail("failure_invalid")
        _sha(self.input_binding_sha256)
        object.__setattr__(self, "ledger_identity", MappingProxyType(_ledger_identity(self.ledger_identity)))
        _assert_claim(self.claim, self.plan)
        terminal = self.failure.terminal_record
        expected = {name: getattr(self.plan, name) for name in (
            "journal_id", "launch_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256",
        )}
        if any(terminal.get(name) != value for name, value in expected.items()):
            _fail("failure_binding_mismatch")
        if self.provenance_sha256 is not None:
            _sha(self.provenance_sha256)

    @property
    def claim_sha256(self) -> str:
        return self.claim.claim_sha256

    def to_dict(self) -> dict[str, Any]:
        """Return the exact payload; publishing-FD identity belongs to the durable file."""
        return {
            "schema_version": "1", "protocol": _PROTOCOL, "plan": self.plan.to_dict(),
            "input_binding_sha256": self.input_binding_sha256,
            "native_failure": self.failure.to_dict(),
            "ledger_identity": dict(self.ledger_identity), "claim": self.claim.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object, *, provenance_sha256: str | None = None) -> NativeRSIFailureEvidence:
        try:
            if type(value) is not dict or set(value) != _PAYLOAD_FIELDS:
                _fail("invalid")
            clean = strict_json(_canonical(value), maximum=MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES)
            if (clean != value or clean["schema_version"] != "1" or clean["protocol"] != _PROTOCOL
                    or type(clean["claim"]) is not dict or set(clean["claim"]) != _CLAIM_FIELDS):
                _fail("invalid")
            result = cls(
                plan=NativeRSIExecutionPlan.from_dict(clean["plan"]),
                failure=NativeTrustedProducerFailure.from_dict(clean["native_failure"]),
                input_binding_sha256=clean["input_binding_sha256"],
                ledger_identity=clean["ledger_identity"], claim=NativeEpisodeClaim(**clean["claim"]),
                provenance_sha256=provenance_sha256,
            )
            if _canonical(result.to_dict()) != _canonical(clean):
                _fail("invalid")
            return result
        except NativeRSIFailureError:
            raise
        except Exception as exc:
            raise NativeRSIFailureError("invalid") from exc


def map_native_failure_to_solver_result(
    request: SolverRequest, plan: NativeRSIExecutionPlan, evidence: NativeRSIFailureEvidence,
) -> SolverResult:
    """Pure failed/cancelled mapping; provenance is required but is not independently trusted."""
    if (not isinstance(request, SolverRequest) or not isinstance(plan, NativeRSIExecutionPlan)
            or not isinstance(evidence, NativeRSIFailureEvidence)
            or evidence.plan != plan or plan.request != request or request.digest() != plan.request_sha256):
        _fail("request_mismatch")
    if evidence.provenance_sha256 is None:
        _fail("provenance_missing")
    # Reconstruct the strict wire so mutable or tampered DTO internals cannot bypass mapping.
    NativeRSIFailureEvidence.from_dict(evidence.to_dict(), provenance_sha256=evidence.provenance_sha256)
    failure = evidence.failure
    return SolverResult(
        episode_id=request.episode_id, request_sha256=request.digest(), status=failure.status,
        candidate_receipt_sha256=None, execution_receipt_sha256=None,
        official_evaluation_receipt_sha256=None, trace_digest=failure.digest(),
        solver_score=None,
        terminal_reason="native_exited_nonzero" if failure.status == "failed" else "native_cancelled",
        solver_provenance=tuple(sorted({
            "native_plan_sha256": plan.plan_sha256,
            "native_failure_sha256": failure.digest(),
            "native_failure_provenance_sha256": evidence.provenance_sha256,
            "native_process_terminal_sha256": failure.terminal_sha256,
            "native_claim_sha256": evidence.claim_sha256,
            "native_exit_code": failure.exit_code,
        }.items())),
    )


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_nlink)


def _directory(batch: Path) -> DirectoryChain:
    try:
        if not isinstance(batch, Path):
            _fail("path_invalid")
        path = batch.expanduser().absolute()
        if (".." in path.parts or "\x00" in str(path) or len(path.parts) > 128
                or len(str(path).encode()) > 4096):
            _fail("path_invalid")
        return DirectoryChain(path, "rsi_native_failure_path_invalid")
    except NativeRSIFailureError:
        raise
    except Exception as exc:
        raise NativeRSIFailureError("path_invalid") from exc


def _assert_no_success(chain: DirectoryChain) -> None:
    chain.check()
    try:
        os.stat(NATIVE_RSI_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    _fail("conflicting_provenance")


def _read_once(chain: DirectoryChain) -> tuple[bytes, os.stat_result]:
    descriptor = None
    try:
        _assert_no_success(chain)
        before = os.stat(NATIVE_RSI_FAILURE_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o400):
            _fail("path_invalid")
        if not 0 < before.st_size <= MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES:
            _fail("invalid")
        descriptor = os.open(NATIVE_RSI_FAILURE_PROVENANCE_NAME,
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=chain.fd)
        if _metadata(os.fstat(descriptor)) != _metadata(before):
            _fail("changed")
        raw = bytearray()
        while len(raw) <= MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        named = os.stat(NATIVE_RSI_FAILURE_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (_metadata(before) != _metadata(after) or _metadata(after) != _metadata(named)
                or len(raw) != before.st_size):
            _fail("changed")
        _assert_no_success(chain)
        return bytes(raw), after
    except FileNotFoundError as exc:
        raise NativeRSIFailureError("missing") from exc
    except NativeRSIFailureError:
        raise
    except Exception as exc:
        raise NativeRSIFailureError("path_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _record(raw: bytes, info: os.stat_result) -> NativeRSIFailureEvidence:
    try:
        value = strict_json(raw, maximum=MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES)
        if type(value) is not dict or set(value) != _PAYLOAD_FIELDS | _IDENTITY_FIELDS:
            _fail("invalid")
        identity = value["file_identity"]
        if (type(identity) is not dict or set(identity) != {"device", "inode"}
                or type(identity["device"]) is not int or type(identity["inode"]) is not int
                or identity["device"] < 0 or identity["inode"] <= 0):
            _fail("invalid")
        if identity != {"device": info.st_dev, "inode": info.st_ino}:
            _fail("changed")
        digest = _sha(value["provenance_sha256"])
        if digest != hashlib.sha256(_canonical({key: item for key, item in value.items()
                                               if key != "provenance_sha256"})).hexdigest():
            _fail("digest_mismatch")
        if _canonical(value) != raw:
            _fail("noncanonical")
        return NativeRSIFailureEvidence.from_dict(
            {key: value[key] for key in _PAYLOAD_FIELDS}, provenance_sha256=digest,
        )
    except NativeRSIFailureError:
        raise
    except Exception as exc:
        raise NativeRSIFailureError("invalid") from exc


def _read(chain: DirectoryChain) -> NativeRSIFailureEvidence:
    raw, before = _read_once(chain)
    evidence = _record(raw, before)
    repeated, after = _read_once(chain)
    if raw != repeated or _metadata(before) != _metadata(after):
        _fail("changed")
    if _record(repeated, after) != evidence:
        _fail("changed")
    _assert_no_success(chain)
    return evidence


def read_native_rsi_failure_provenance(batch: Path) -> NativeRSIFailureEvidence:
    """Read an existing canonical sidecar twice; never initialize or repair anything."""
    chain = _directory(batch)
    try:
        return _read(chain)
    finally:
        chain.close()


def persist_native_rsi_failure_provenance(batch: Path, evidence: NativeRSIFailureEvidence) -> str:
    """Create once with publishing-FD inode binding; identical replay is read-only.

    Partial files stay as crash evidence. No cleanup, replacement or candidate authority.
    """
    if not isinstance(evidence, NativeRSIFailureEvidence):
        _fail("invalid")
    clean = NativeRSIFailureEvidence.from_dict(evidence.to_dict()).to_dict()
    chain = _directory(batch)
    descriptor = None
    try:
        _assert_no_success(chain)
        try:
            if evidence.provenance_sha256 is not None:
                existing = _read(chain)
                if existing != evidence:
                    _fail("conflict")
                return existing.provenance_sha256
            descriptor = os.open(NATIVE_RSI_FAILURE_PROVENANCE_NAME,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o400, dir_fd=chain.fd)
        except FileExistsError:
            existing = _read(chain)
            if _canonical(existing.to_dict()) != _canonical(clean):
                _fail("conflict")
            return existing.provenance_sha256
        os.fchmod(descriptor, 0o400)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            _fail("changed")
        body = {**clean, "file_identity": {"device": opened.st_dev, "inode": opened.st_ino}}
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        raw = _canonical({**body, "provenance_sha256": digest})
        view = memoryview(raw)
        while view:
            _assert_no_success(chain)
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("write_failed")
            view = view[count:]
        os.fsync(descriptor)
        frozen = os.fstat(descriptor)
        if (frozen.st_dev, frozen.st_ino) != (opened.st_dev, opened.st_ino):
            _fail("changed")
        _assert_no_success(chain)
        retained = _read(chain)
        named = os.stat(NATIVE_RSI_FAILURE_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (retained != replace(evidence, provenance_sha256=digest)
                or _metadata(frozen) != _metadata(os.fstat(descriptor))
                or _metadata(frozen) != _metadata(named)):
            _fail("changed")
        os.fsync(chain.fd)
        _assert_no_success(chain)
        final = _read(chain)
        final_named = os.stat(NATIVE_RSI_FAILURE_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (final != retained or _metadata(frozen) != _metadata(os.fstat(descriptor))
                or _metadata(frozen) != _metadata(final_named)):
            _fail("changed")
        return digest
    except NativeRSIFailureError:
        raise
    except Exception as exc:
        raise NativeRSIFailureError("write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()


__all__ = [
    "NATIVE_RSI_FAILURE_PROVENANCE_NAME", "NativeRSIFailureError", "NativeRSIFailureEvidence",
    "map_native_failure_to_solver_result", "persist_native_rsi_failure_provenance",
    "read_native_rsi_failure_provenance",
]
