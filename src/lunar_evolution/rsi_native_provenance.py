"""Create-only local native RSI provenance, without execution or memory authority."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from .rsi_native_plan import NativeRSIExecutionPlan

NATIVE_RSI_PROVENANCE_NAME = "native-rsi.provenance.json"
MAX_NATIVE_RSI_PROVENANCE_BYTES = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")
_PAYLOAD_FIELDS = {
    "schema_version", "protocol", "plan", "input_binding_sha256", "retained_evidence_sha256",
    "publication_journal_sha256", "producer_execution_receipt_sha256", "bundle",
}
_IDENTITY_FIELDS = {"file_identity", "provenance_sha256"}
_DTO_TYPES = {"candidate": NativeCandidateRecord, "execution": NativeExecutionReceipt,
              "evaluation": NativeEvaluationReceipt, "publication": NativePublicationReceipt}


class NativeRSIProvenanceError(ValueError):
    """Fixed public codes for missing, conflicting, malformed or replaced provenance."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_native_provenance_" + code
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise NativeRSIProvenanceError(code)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=MAX_NATIVE_RSI_PROVENANCE_BYTES)


def _json_shape(value: object) -> None:
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _fail("invalid")
        for item in value.values():
            _json_shape(item)
    elif type(value) is list:
        for item in value:
            _json_shape(item)
    elif value is not None and type(value) not in {str, bool, int, float}:
        _fail("invalid")


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("invalid")
    return value


def _payload(value: object) -> dict[str, Any]:
    """Validate all DTOs without treating provenance as an independent verdict."""
    try:
        if type(value) is not dict or set(value) != _PAYLOAD_FIELDS:
            _fail("invalid")
        _json_shape(value)
        clean = strict_json(_canonical(value), maximum=MAX_NATIVE_RSI_PROVENANCE_BYTES)
        if clean["schema_version"] != "1" or clean["protocol"] != "lunar-native-rsi-provenance-v1":
            _fail("invalid")
        for name in ("input_binding_sha256", "retained_evidence_sha256", "publication_journal_sha256",
                     "producer_execution_receipt_sha256"):
            _sha(clean[name])
        plan = NativeRSIExecutionPlan.from_dict(clean["plan"])
        if _canonical(plan.to_dict()) != _canonical(clean["plan"]):
            _fail("invalid")
        bundle = clean["bundle"]
        if type(bundle) is not dict or set(bundle) != set(_DTO_TYPES):
            _fail("invalid")
        receipts = {}
        expected = {"request_sha256": plan.request_sha256, "contract_sha256": plan.request.contract_sha256,
                    "evaluator_sha256": plan.request.evaluator_sha256,
                    "environment_sha256": plan.request.environment_sha256,
                    "memory_snapshot_sha256": plan.memory_snapshot_sha256}
        for name, dto_type in _DTO_TYPES.items():
            receipt = dto_type.from_dict(bundle[name])
            if _canonical(receipt.to_dict()) != _canonical(bundle[name]):
                _fail("invalid")
            if any(getattr(receipt, key) != pin for key, pin in expected.items()):
                _fail("binding_mismatch")
            receipts[name] = receipt
        if len({receipt.candidate_id for receipt in receipts.values()}) != 1:
            _fail("candidate_mismatch")
        return clean
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("invalid") from exc


def _record(raw: bytes, info: os.stat_result) -> dict[str, Any]:
    try:
        value = strict_json(raw, maximum=MAX_NATIVE_RSI_PROVENANCE_BYTES)
        if type(value) is not dict or set(value) != _PAYLOAD_FIELDS | _IDENTITY_FIELDS:
            _fail("invalid")
        _payload({key: value[key] for key in _PAYLOAD_FIELDS})
        identity = value["file_identity"]
        if (type(identity) is not dict or set(identity) != {"device", "inode"}
                or type(identity["device"]) is not int or identity["device"] < 0
                or type(identity["inode"]) is not int or identity["inode"] <= 0):
            _fail("invalid")
        if identity != {"device": info.st_dev, "inode": info.st_ino}:
            _fail("changed")
        digest = _sha(value["provenance_sha256"])
        if digest != hashlib.sha256(_canonical({key: item for key, item in value.items()
                                               if key != "provenance_sha256"})).hexdigest():
            _fail("digest_mismatch")
        if _canonical(value) != raw:
            _fail("noncanonical")
        return value
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("invalid") from exc


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_nlink)


def _read_once(chain: DirectoryChain) -> tuple[bytes, os.stat_result]:
    descriptor = None
    try:
        chain.check()
        before = os.stat(NATIVE_RSI_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o400):
            _fail("path_invalid")
        if not 0 < before.st_size <= MAX_NATIVE_RSI_PROVENANCE_BYTES:
            _fail("invalid")
        descriptor = os.open(NATIVE_RSI_PROVENANCE_NAME,
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=chain.fd)
        if _metadata(os.fstat(descriptor)) != _metadata(before):
            _fail("changed")
        raw = bytearray()
        while len(raw) <= MAX_NATIVE_RSI_PROVENANCE_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_NATIVE_RSI_PROVENANCE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        named = os.stat(NATIVE_RSI_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (_metadata(before) != _metadata(after) or _metadata(after) != _metadata(named)
                or len(raw) != before.st_size):
            _fail("changed")
        chain.check()
        return bytes(raw), after
    except FileNotFoundError as exc:
        raise NativeRSIProvenanceError("missing") from exc
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("path_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read(chain: DirectoryChain) -> dict[str, Any]:
    try:
        raw, before = _read_once(chain)
        value = _record(raw, before)
        repeated, after = _read_once(chain)
        if raw != repeated or _metadata(before) != _metadata(after):
            _fail("changed")
        _record(repeated, after)
        chain.check()
        return value
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("changed") from exc


def _directory(batch: Path) -> DirectoryChain:
    try:
        if not isinstance(batch, Path):
            _fail("path_invalid")
        path = batch.expanduser().absolute()
        if (".." in path.parts or "\x00" in str(path) or len(path.parts) > 128
                or len(str(path).encode()) > 4096):
            _fail("path_invalid")
        return DirectoryChain(path, "rsi_native_provenance_path_invalid")
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("path_invalid") from exc


def read_native_rsi_provenance(batch: Path) -> dict[str, Any]:
    """Read existing canonical evidence twice; never initialize or repair its directory."""
    chain = _directory(batch)
    try:
        return _read(chain)
    finally:
        chain.close()


def persist_native_rsi_provenance(batch: Path, payload: dict[str, Any]) -> str:
    """Create one immutable sidecar, or read back an identical, already valid payload.

    Failed writes are retained as recovery evidence. This helper never deletes, replaces, repairs,
    launches native work, or grants memory admission. The scheduler supplies the observed pins.
    """
    clean = _payload(payload)
    chain = _directory(batch)
    descriptor = None
    try:
        chain.check()
        try:
            descriptor = os.open(NATIVE_RSI_PROVENANCE_NAME,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o400, dir_fd=chain.fd)
        except FileExistsError:
            existing = _read(chain)
            if _canonical({key: existing[key] for key in _PAYLOAD_FIELDS}) != _canonical(clean):
                _fail("conflict")
            return existing["provenance_sha256"]
        os.fchmod(descriptor, 0o400)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            _fail("changed")
        body = {**clean, "file_identity": {"device": opened.st_dev, "inode": opened.st_ino}}
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        raw = _canonical({**body, "provenance_sha256": digest})
        view = memoryview(raw)
        while view:
            chain.check()
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("write_failed")
            view = view[count:]
        os.fsync(descriptor)
        chain.check()
        retained = _read(chain)
        if retained != {**body, "provenance_sha256": digest}:
            _fail("changed")
        os.fsync(chain.fd)
        chain.check()
        return digest
    except NativeRSIProvenanceError:
        raise
    except Exception as exc:
        raise NativeRSIProvenanceError("write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()


__all__ = [
    "NATIVE_RSI_PROVENANCE_NAME",
    "NativeRSIProvenanceError",
    "persist_native_rsi_provenance",
    "read_native_rsi_provenance",
]
