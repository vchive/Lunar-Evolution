"""Known all-rejected evidence and independently pinned, create-only provenance.

DTO parsing and pure mapping establish wire associations only. They do not verify
native filesystem/ledger truth, settle an episode or create an execution permit.
The original provider and owner must verify native evidence and acknowledge C1/P/C2.
"""

from __future__ import annotations

import gc
import hashlib
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path, PosixPath, WindowsPath
from types import MappingProxyType
from typing import Any, NoReturn

from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_lineage import MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES, MAX_LINEAGE_BATCHES
from .producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from .producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
)
from .python_producer_admission_handoff import PythonProducerAdmissionHandoffFilePin
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_provenance_names import (
    NATIVE_RSI_PROVENANCE_NAMES,
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
)
from .rsi_store import NativeEpisodeClaim, RSILedger

MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES = 1024 * 1024
_PROTOCOL = "lunar-native-rsi-rejection-provenance-v2"
_C1_PROTOCOL = "lunar-rsi-rejection-lineage-c1-v2"
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MAX_INT = 2**64 - 1
_PIN_FIELDS = {
    "name", "sha256", "size", "device", "inode", "parent_device", "parent_inode",
    "mode", "nlink", "mtime_ns", "ctime_ns",
}
_C1_FIELDS = {
    "schema_version", "protocol", "run_id", "episode_id", "journal_id", "ordinal",
    "checkpoint_sha256", "before_sha256", "rejected_sha256", "prepared_journal_sha256",
    "terminal_journal_sha256", "rejection_manifest_sha256", "terminal_marker_sha256",
    "candidate_ids", "archive_sha256", "state_sha256", "retained_bytes",
}
_PAYLOAD_FIELDS = {
    "schema_version", "protocol", "plan", "input_binding_sha256", "ledger_identity",
    "claim", "lineage", "rejected", "terminal", "producer_execution_receipt_sha256",
    "producer_output_sha256", "execution_receipt_sha256s", "evaluation_receipt_sha256s",
    "retained_evidence_sha256s",
}
_CLAIM_FIELDS = {
    "episode_id", "request_sha256", "plan_sha256", "status", "claim_sha256", "created_at",
}


class NativeRSIRejectionError(ValueError):
    """Fixed refusal codes without paths, credentials or producer prose."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_native_rejection_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise NativeRSIRejectionError(code)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise NativeRSIRejectionError("wire_invalid") from exc


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("identity_invalid")
    return value


def _integer(value: object, *, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("integer_invalid")
    return value


def _shape(value: object, depth: int = 0) -> None:
    if depth > 32:
        _fail("shape_invalid")
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _fail("shape_invalid")
        for item in value.values():
            _shape(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _shape(item, depth + 1)
    elif value is not None and type(value) not in {str, bool, int, float}:
        _fail("shape_invalid")


def _plain_mapping(value: object) -> dict[str, Any]:
    """Inspect a proxy's backing object before any mapping method can run."""
    if type(value) is dict:
        return value
    if type(value) is MappingProxyType:
        backing = gc.get_referents(value)
        if len(backing) == 1 and type(backing[0]) is dict:
            return backing[0]
    _fail("shape_invalid")


def _dto_shape(value: object) -> None:
    """Refuse callback-bearing nested values before serialization or comparison.

    Frozen DTOs can still be polluted with ``object.__setattr__``. Exact roots do
    not suffice: inspect their fields and only builtin containers, including the
    exact dict behind our ledger proxy, without calling DTO or mapping methods.
    """
    allowed = {
        NativeRSIExecutionPlan, SolverRequest, NativeEpisodeClaim,
        ProducerBundlePublicationJournal, ProducerBundlePublicationCandidate,
        ProducerLineageRejectedTerminalV2, PythonProducerAdmissionHandoffFilePin,
        NativeRSIRejectionEvidence, RejectionLineageC1Binding, NativeRSIRejectionFilePin,
    }
    remaining = 65536
    active: set[int] = set()

    def visit(item: object, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if depth > 32 or remaining < 0:
            _fail("shape_invalid")
        item_type = type(item)
        if item is None or item_type in {str, bool, int, float}:
            return
        if item_type not in allowed | {dict, list, tuple, MappingProxyType}:
            _fail("shape_invalid")
        identity = id(item)
        if identity in active:
            _fail("shape_invalid")
        active.add(identity)
        try:
            if item_type in allowed:
                names = tuple(field.name for field in fields(item_type))
                try:
                    storage = object.__getattribute__(item, "__dict__")
                except AttributeError:
                    storage = None
                if storage is not None and (
                        type(storage) is not dict or any(type(key) is not str for key in storage)
                        or set(storage) != set(names)):
                    _fail("shape_invalid")
                for name in names:
                    visit(object.__getattribute__(item, name), depth + 1)
            elif item_type in {dict, MappingProxyType}:
                mapping = _plain_mapping(item)
                if any(type(key) is not str for key in mapping):
                    _fail("shape_invalid")
                for nested in mapping.values():
                    visit(nested, depth + 1)
            else:
                for nested in item:
                    visit(nested, depth + 1)
        except (AttributeError, RecursionError) as exc:
            raise NativeRSIRejectionError("shape_invalid") from exc
        finally:
            active.remove(identity)

    visit(value, 0)


def _ids(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not 1 <= len(value) <= 32:
        _fail("candidate_ids_invalid")
    result = tuple(_identifier(item) for item in value)
    if len(set(result)) != len(result):
        _fail("candidate_ids_invalid")
    return result


def _digests(value: object, count: int) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) != count:
        _fail("receipt_cardinality_invalid")
    return tuple(_sha(item) for item in value)


def _reparse(value: Any, dto_type: Any) -> Any:
    _dto_shape(value)
    try:
        return dto_type.from_dict(value.to_dict())
    except NativeRSIRejectionError:
        raise
    except Exception as exc:
        raise NativeRSIRejectionError("dto_invalid") from exc


@dataclass(frozen=True, slots=True)
class NativeRSIRejectionFilePin:
    """Original publishing-FD observation, independently retained by the owner."""

    name: str
    sha256: str
    size: int
    device: int
    inode: int
    parent_device: int
    parent_inode: int
    mode: int = 0o400
    nlink: int = 1
    mtime_ns: int = 0
    ctime_ns: int = 0

    def __post_init__(self) -> None:
        if (type(self) is not NativeRSIRejectionFilePin or type(self.name) is not str
                or self.name != NATIVE_RSI_REJECTION_PROVENANCE_NAME):
            _fail("file_pin_invalid")
        _sha(self.sha256)
        _integer(self.size, minimum=1, maximum=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)
        for field in ("device", "parent_device", "mtime_ns", "ctime_ns"):
            _integer(getattr(self, field))
        for field in ("inode", "parent_inode"):
            _integer(getattr(self, field), minimum=1)
        if type(self.mode) is not int or self.mode != 0o400 or type(self.nlink) is not int or self.nlink != 1:
            _fail("file_pin_invalid")

    def to_dict(self) -> dict[str, Any]:
        _dto_shape(self)
        return {field: getattr(self, field) for field in _PIN_FIELDS}

    @classmethod
    def from_dict(cls, value: object) -> NativeRSIRejectionFilePin:
        _shape(value)
        if cls is not NativeRSIRejectionFilePin or type(value) is not dict or set(value) != _PIN_FIELDS:
            _fail("file_pin_invalid")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class RejectionLineageC1Binding:
    """Held C1 associations/accounting, not an owner or acknowledgment permit."""

    run_id: str
    episode_id: str
    journal_id: str
    ordinal: int
    checkpoint_sha256: str
    before_sha256: str
    rejected_sha256: str
    prepared_journal_sha256: str
    terminal_journal_sha256: str
    rejection_manifest_sha256: str
    terminal_marker_sha256: str
    candidate_ids: tuple[str, ...]
    archive_sha256: str
    state_sha256: str
    retained_bytes: int

    def __post_init__(self) -> None:
        if type(self) is not RejectionLineageC1Binding:
            _fail("lineage_invalid")
        for field in ("run_id", "episode_id", "journal_id"):
            _identifier(getattr(self, field))
        _integer(self.ordinal, maximum=MAX_LINEAGE_BATCHES - 1)
        for field in ("checkpoint_sha256", "before_sha256", "rejected_sha256",
                      "prepared_journal_sha256", "terminal_journal_sha256",
                      "rejection_manifest_sha256", "terminal_marker_sha256",
                      "archive_sha256", "state_sha256"):
            _sha(getattr(self, field))
        _ids(self.candidate_ids)
        _integer(self.retained_bytes, maximum=MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES)

    def to_dict(self) -> dict[str, Any]:
        _dto_shape(self)
        result = {field: getattr(self, field) for field in _C1_FIELDS - {"schema_version", "protocol"}}
        result.update(schema_version="2", protocol=_C1_PROTOCOL, candidate_ids=list(self.candidate_ids))
        return result

    @classmethod
    def from_dict(cls, value: object) -> RejectionLineageC1Binding:
        _shape(value)
        if cls is not RejectionLineageC1Binding or type(value) is not dict or set(value) != _C1_FIELDS:
            _fail("lineage_invalid")
        if value["schema_version"] != "2" or value["protocol"] != _C1_PROTOCOL or type(value["candidate_ids"]) is not list:
            _fail("lineage_invalid")
        raw = {key: item for key, item in value.items() if key not in {"schema_version", "protocol"}}
        raw["candidate_ids"] = tuple(raw["candidate_ids"])
        return cls(**raw)


def _ledger_identity(value: object) -> dict[str, Any]:
    value = _plain_mapping(value)
    _shape(value)
    if set(value) != {"database", "device", "inode"}:
        _fail("ledger_invalid")
    database = value["database"]
    if (type(database) is not str or not Path(database).is_absolute() or "\x00" in database
            or ".." in Path(database).parts or len(database.encode()) > 4096
            or database != str(Path(database).absolute())):
        _fail("ledger_invalid")
    return {"database": database, "device": _integer(value["device"]),
            "inode": _integer(value["inode"], minimum=1)}


@dataclass(frozen=True, slots=True)
class NativeRSIRejectionEvidence:
    """Strict native association; parsing alone never verifies trust or settles a claim."""

    plan: NativeRSIExecutionPlan
    input_binding_sha256: str
    ledger_identity: Mapping[str, Any]
    claim: NativeEpisodeClaim
    lineage: RejectionLineageC1Binding
    rejected: ProducerLineageRejectedTerminalV2
    terminal: ProducerBundlePublicationJournal
    producer_execution_receipt_sha256: str
    producer_output_sha256: str
    execution_receipt_sha256s: tuple[str, ...]
    evaluation_receipt_sha256s: tuple[str, ...]
    retained_evidence_sha256s: tuple[str, ...]
    provenance_sha256: str | None = None
    provenance_file_pin: NativeRSIRejectionFilePin | None = None

    def __post_init__(self) -> None:
        if (type(self) is not NativeRSIRejectionEvidence or type(self.plan) is not NativeRSIExecutionPlan
                or type(self.claim) is not NativeEpisodeClaim or type(self.lineage) is not RejectionLineageC1Binding
                or type(self.rejected) is not ProducerLineageRejectedTerminalV2
                or type(self.terminal) is not ProducerBundlePublicationJournal):
            _fail("dto_invalid")
        _dto_shape(self)
        plan = _reparse(self.plan, NativeRSIExecutionPlan)
        lineage = _reparse(self.lineage, RejectionLineageC1Binding)
        rejected = _reparse(self.rejected, ProducerLineageRejectedTerminalV2)
        terminal = _reparse(self.terminal, ProducerBundlePublicationJournal)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "lineage", lineage)
        object.__setattr__(self, "rejected", rejected)
        object.__setattr__(self, "terminal", terminal)
        object.__setattr__(self, "ledger_identity", MappingProxyType(_ledger_identity(self.ledger_identity)))
        claim = self.claim
        if (claim.status != "started" or claim.episode_id != plan.request.episode_id
                or claim.request_sha256 != plan.request_sha256 or claim.plan_sha256 != plan.plan_sha256
                or type(claim.created_at) is not str or not claim.created_at.strip()
                or len(claim.created_at.encode()) > 128
                or claim.claim_sha256 != RSILedger._native_claim_digest(
                    claim.episode_id, claim.request_sha256, claim.plan_sha256)):
            _fail("claim_mismatch")
        _sha(claim.claim_sha256)
        for value in (self.input_binding_sha256, self.producer_execution_receipt_sha256, self.producer_output_sha256):
            _sha(value)
        if (terminal.state != "all_rejected" or terminal.publication_phase != "committed"
                or terminal.run_id != plan.run_id or terminal.journal_id != plan.journal_id
                or terminal.parent_task_id != plan.parent_task_id or terminal.task_id != plan.task_id
                or terminal.contract_sha256 != plan.request.contract_sha256
                or terminal.environment_sha256 != plan.request.environment_sha256
                or terminal.evaluator_kind != plan.evaluator_kind
                or terminal.evaluator_fingerprint != plan.evaluator_fingerprint
                or terminal.native_execution_receipt_sha256 != self.producer_execution_receipt_sha256):
            _fail("terminal_mismatch")
        ids = tuple(item.candidate_id for item in terminal.candidates)
        count = len(ids)
        executions = _digests(self.execution_receipt_sha256s, count)
        evaluations = _digests(self.evaluation_receipt_sha256s, count)
        _digests(self.retained_evidence_sha256s, count)
        if (ids != lineage.candidate_ids or ids != rejected.candidate_ids
                or executions != tuple(item.execution_receipt_sha256 for item in terminal.candidates)
                or evaluations != tuple(item.evaluation_receipt_sha256 for item in terminal.candidates)):
            _fail("candidate_receipts_mismatch")
        expected = {
            "run_id": plan.run_id, "episode_id": plan.request.episode_id, "journal_id": plan.journal_id,
            "ordinal": lineage.ordinal, "before_sha256": lineage.before_sha256,
            "prepared_journal_sha256": lineage.prepared_journal_sha256,
            "terminal_journal_sha256": terminal.digest(),
            "rejection_manifest_sha256": lineage.rejection_manifest_sha256,
            "terminal_marker_sha256": terminal.terminal_marker_sha256,
            "archive_sha256": terminal.base_archive_sha256, "state_sha256": terminal.base_state_sha256,
        }
        if (any(getattr(rejected, key) != value for key, value in expected.items())
                or any(getattr(lineage, key) != value for key, value in expected.items())
                or lineage.rejected_sha256 != rejected.digest()):
            _fail("lineage_mismatch")
        if (self.provenance_sha256 is None) != (self.provenance_file_pin is None):
            _fail("provenance_pair_invalid")
        if self.provenance_sha256 is not None:
            _sha(self.provenance_sha256)
            if type(self.provenance_file_pin) is not NativeRSIRejectionFilePin:
                _fail("file_pin_invalid")
            object.__setattr__(self, "provenance_file_pin", NativeRSIRejectionFilePin.from_dict(self.provenance_file_pin.to_dict()))
            body = {**self.to_dict(), "file_identity": {
                "device": self.provenance_file_pin.device, "inode": self.provenance_file_pin.inode,
            }}
            raw = _canonical({**body, "provenance_sha256": self.provenance_sha256})
            if (hashlib.sha256(_canonical(body)).hexdigest() != self.provenance_sha256
                    or hashlib.sha256(raw).hexdigest() != self.provenance_file_pin.sha256
                    or len(raw) != self.provenance_file_pin.size):
                _fail("provenance_pin_mismatch")
        _canonical(self.to_dict())

    @property
    def claim_sha256(self) -> str:
        return self.claim.claim_sha256

    def to_dict(self) -> dict[str, Any]:
        """Payload excludes read-back pin/digest and C2 to avoid circular identities."""
        _dto_shape(self)
        return {
            "schema_version": "2", "protocol": _PROTOCOL, "plan": self.plan.to_dict(),
            "input_binding_sha256": self.input_binding_sha256, "ledger_identity": dict(self.ledger_identity),
            "claim": self.claim.to_dict(), "lineage": self.lineage.to_dict(),
            "rejected": self.rejected.to_dict(), "terminal": self.terminal.to_dict(),
            "producer_execution_receipt_sha256": self.producer_execution_receipt_sha256,
            "producer_output_sha256": self.producer_output_sha256,
            "execution_receipt_sha256s": list(self.execution_receipt_sha256s),
            "evaluation_receipt_sha256s": list(self.evaluation_receipt_sha256s),
            "retained_evidence_sha256s": list(self.retained_evidence_sha256s),
        }

    @classmethod
    def from_dict(cls, value: object, *, provenance_sha256: str | None = None,
                  provenance_file_pin: NativeRSIRejectionFilePin | None = None) -> NativeRSIRejectionEvidence:
        try:
            _shape(value)
            if cls is not NativeRSIRejectionEvidence or type(value) is not dict or set(value) != _PAYLOAD_FIELDS:
                _fail("invalid")
            clean = strict_json(_canonical(value), maximum=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)
            if (clean["schema_version"] != "2" or clean["protocol"] != _PROTOCOL
                    or type(clean["claim"]) is not dict or set(clean["claim"]) != _CLAIM_FIELDS):
                _fail("invalid")
            for field in ("execution_receipt_sha256s", "evaluation_receipt_sha256s", "retained_evidence_sha256s"):
                if type(clean[field]) is not list:
                    _fail("invalid")
            result = cls(
                plan=NativeRSIExecutionPlan.from_dict(clean["plan"]),
                input_binding_sha256=clean["input_binding_sha256"], ledger_identity=clean["ledger_identity"],
                claim=NativeEpisodeClaim(**clean["claim"]), lineage=RejectionLineageC1Binding.from_dict(clean["lineage"]),
                rejected=ProducerLineageRejectedTerminalV2.from_dict(clean["rejected"]),
                terminal=ProducerBundlePublicationJournal.from_dict(clean["terminal"]),
                producer_execution_receipt_sha256=clean["producer_execution_receipt_sha256"],
                producer_output_sha256=clean["producer_output_sha256"],
                execution_receipt_sha256s=tuple(clean["execution_receipt_sha256s"]),
                evaluation_receipt_sha256s=tuple(clean["evaluation_receipt_sha256s"]),
                retained_evidence_sha256s=tuple(clean["retained_evidence_sha256s"]),
                provenance_sha256=provenance_sha256, provenance_file_pin=provenance_file_pin,
            )
            if _canonical(result.to_dict()) != _canonical(clean):
                _fail("invalid")
            return result
        except NativeRSIRejectionError:
            raise
        except Exception as exc:
            raise NativeRSIRejectionError("invalid") from exc


def map_native_rejection_to_solver_result(
    request: SolverRequest, plan: NativeRSIExecutionPlan, evidence: NativeRSIRejectionEvidence,
) -> SolverResult:
    """Pure failed mapping; even a parsed pin proves no ledger/filesystem trust."""
    _dto_shape(request)
    _dto_shape(plan)
    _dto_shape(evidence)
    if (type(request) is not SolverRequest or type(plan) is not NativeRSIExecutionPlan
            or type(evidence) is not NativeRSIRejectionEvidence or evidence.plan != plan
            or plan.request != request or request.digest() != plan.request_sha256):
        _fail("request_mismatch")
    if evidence.provenance_sha256 is None or evidence.provenance_file_pin is None:
        _fail("provenance_missing")
    clean = NativeRSIRejectionEvidence.from_dict(evidence.to_dict(), provenance_sha256=evidence.provenance_sha256,
                                               provenance_file_pin=evidence.provenance_file_pin)
    return SolverResult(
        episode_id=request.episode_id, request_sha256=request.digest(), status="failed",
        candidate_receipt_sha256=None, execution_receipt_sha256=None,
        official_evaluation_receipt_sha256=None, trace_digest=clean.producer_output_sha256,
        solver_score=None, terminal_reason="native_all_rejected",
        solver_provenance=tuple(sorted({
            "native_plan_sha256": plan.plan_sha256, "native_claim_sha256": clean.claim_sha256,
            "native_rejection_provenance_sha256": clean.provenance_sha256,
            "native_rejection_lineage_sha256": clean.rejected.digest(),
            "native_rejection_terminal_sha256": clean.terminal.digest(),
            "native_rejection_manifest_sha256": clean.lineage.rejection_manifest_sha256,
            "native_rejection_c1_sha256": clean.lineage.checkpoint_sha256,
            "native_producer_execution_receipt_sha256": clean.producer_execution_receipt_sha256,
            "native_producer_output_sha256": clean.producer_output_sha256,
        }.items())),
    )


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_nlink)


def _directory(batch: Path) -> DirectoryChain:
    try:
        if type(batch) not in {Path, PosixPath, WindowsPath}:
            _fail("path_invalid")
        path = batch.expanduser().absolute()
        if ".." in path.parts or "\x00" in str(path) or len(path.parts) > 128 or len(str(path).encode()) > 4096:
            _fail("path_invalid")
        return DirectoryChain(path, "rsi_native_rejection_path_invalid")
    except NativeRSIRejectionError:
        raise
    except Exception as exc:
        raise NativeRSIRejectionError("path_invalid") from exc


def _assert_exclusive(chain: DirectoryChain) -> None:
    chain.check()
    for name in NATIVE_RSI_PROVENANCE_NAMES:
        if name == NATIVE_RSI_REJECTION_PROVENANCE_NAME:
            continue
        try:
            os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        _fail("conflicting_provenance")


def _pin(raw: bytes, info: os.stat_result, parent: os.stat_result) -> NativeRSIRejectionFilePin:
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 1:
        _fail("file_pin_invalid")
    return NativeRSIRejectionFilePin(
        NATIVE_RSI_REJECTION_PROVENANCE_NAME, hashlib.sha256(raw).hexdigest(), len(raw),
        info.st_dev, info.st_ino, parent.st_dev, parent.st_ino,
        mode=stat.S_IMODE(info.st_mode), nlink=info.st_nlink, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
    )


def _read_once(chain: DirectoryChain, expected: NativeRSIRejectionFilePin) -> tuple[bytes, os.stat_result]:
    descriptor = None
    try:
        _assert_exclusive(chain)
        parent = os.fstat(chain.fd)
        if (parent.st_dev, parent.st_ino) != (expected.parent_device, expected.parent_inode):
            _fail("changed")
        before = os.stat(NATIVE_RSI_REJECTION_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o400
                or not 0 < before.st_size <= MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES):
            _fail("path_invalid")
        descriptor = os.open(NATIVE_RSI_REJECTION_PROVENANCE_NAME,
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=chain.fd)
        if _metadata(before) != _metadata(os.fstat(descriptor)):
            _fail("changed")
        raw = bytearray()
        while len(raw) <= MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        named = os.stat(NATIVE_RSI_REJECTION_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if (_metadata(before) != _metadata(after) or _metadata(after) != _metadata(named)
                or len(raw) != after.st_size or _pin(bytes(raw), after, parent) != expected):
            _fail("changed")
        _assert_exclusive(chain)
        return bytes(raw), after
    except FileNotFoundError as exc:
        raise NativeRSIRejectionError("missing") from exc
    except NativeRSIRejectionError:
        raise
    except Exception as exc:
        raise NativeRSIRejectionError("path_invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _record(raw: bytes, info: os.stat_result, pin: NativeRSIRejectionFilePin) -> NativeRSIRejectionEvidence:
    try:
        value = strict_json(raw, maximum=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)
        _shape(value)
        if type(value) is not dict or set(value) != _PAYLOAD_FIELDS | {"file_identity", "provenance_sha256"}:
            _fail("invalid")
        if value["file_identity"] != {"device": info.st_dev, "inode": info.st_ino}:
            _fail("changed")
        identity = value["file_identity"]
        if type(identity) is not dict or set(identity) != {"device", "inode"}:
            _fail("invalid")
        _integer(identity["device"])
        _integer(identity["inode"], minimum=1)
        digest = _sha(value["provenance_sha256"])
        if digest != hashlib.sha256(_canonical({key: item for key, item in value.items()
                                               if key != "provenance_sha256"})).hexdigest():
            _fail("digest_mismatch")
        if _canonical(value) != raw:
            _fail("noncanonical")
        return NativeRSIRejectionEvidence.from_dict({key: value[key] for key in _PAYLOAD_FIELDS},
                                                  provenance_sha256=digest, provenance_file_pin=pin)
    except NativeRSIRejectionError:
        raise
    except Exception as exc:
        raise NativeRSIRejectionError("invalid") from exc


def _read(chain: DirectoryChain, pin: NativeRSIRejectionFilePin) -> NativeRSIRejectionEvidence:
    raw, before = _read_once(chain, pin)
    evidence = _record(raw, before, pin)
    repeated, after = _read_once(chain, pin)
    if raw != repeated or _metadata(before) != _metadata(after) or _record(repeated, after, pin) != evidence:
        _fail("changed")
    _assert_exclusive(chain)
    return evidence


def read_native_rsi_rejection_provenance(
    batch: Path, *, expected_file_pin: NativeRSIRejectionFilePin,
) -> NativeRSIRejectionEvidence:
    """Read twice under an independent held pin; never discover, adopt or refresh it."""
    if type(expected_file_pin) is not NativeRSIRejectionFilePin:
        _fail("file_pin_invalid")
    _dto_shape(expected_file_pin)
    pin = NativeRSIRejectionFilePin.from_dict(expected_file_pin.to_dict())
    chain = _directory(batch)
    try:
        return _read(chain, pin)
    finally:
        chain.close()


def persist_native_rsi_rejection_provenance(
    batch: Path, evidence: NativeRSIRejectionEvidence, *, retained_bytes: int,
) -> tuple[str, NativeRSIRejectionFilePin]:
    """Fresh create only; return the original publishing-FD pin, never an adopted pin.

    Original owner acknowledgment remains separate. Partial/orphan files stay as
    evidence and every subsequent call refuses them, even if their payload matches.
    """
    if type(evidence) is not NativeRSIRejectionEvidence:
        _fail("dto_invalid")
    _dto_shape(evidence)
    if evidence.provenance_sha256 is not None or evidence.provenance_file_pin is not None:
        _fail("fresh_evidence_required")
    clean = NativeRSIRejectionEvidence.from_dict(evidence.to_dict()).to_dict()
    _integer(retained_bytes, maximum=MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES)
    if retained_bytes != evidence.lineage.retained_bytes:
        _fail("retained_bytes_mismatch")
    worst = _canonical({**clean, "file_identity": {"device": _MAX_INT, "inode": _MAX_INT},
                        "provenance_sha256": "f" * 64})
    if retained_bytes + len(worst) > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("capacity_exceeded")
    chain = _directory(batch)
    descriptor = None
    try:
        _assert_exclusive(chain)
        try:
            descriptor = os.open(NATIVE_RSI_REJECTION_PROVENANCE_NAME,
                                 os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o400, dir_fd=chain.fd)
        except FileExistsError:
            _fail("already_exists")
        os.fchmod(descriptor, 0o400)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode) != 0o400 or opened.st_nlink != 1:
            _fail("changed")
        _integer(opened.st_dev)
        _integer(opened.st_ino, minimum=1)
        body = {**clean, "file_identity": {"device": opened.st_dev, "inode": opened.st_ino}}
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        raw = _canonical({**body, "provenance_sha256": digest})
        view = memoryview(raw)
        while view:
            _assert_exclusive(chain)
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("write_failed")
            view = view[count:]
        os.fsync(descriptor)
        _assert_exclusive(chain)
        frozen = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (frozen.st_dev, frozen.st_ino)
                or frozen.st_size != len(raw)):
            _fail("changed")
        original_pin = _pin(raw, frozen, os.fstat(chain.fd))
        retained = _read(chain, original_pin)
        if retained.provenance_sha256 != digest or _canonical(retained.to_dict()) != _canonical(clean):
            _fail("changed")
        os.fsync(chain.fd)
        final = _read(chain, original_pin)
        if final != retained:
            _fail("changed")
        _assert_exclusive(chain)
        named = os.stat(NATIVE_RSI_REJECTION_PROVENANCE_NAME, dir_fd=chain.fd, follow_symlinks=False)
        if _metadata(frozen) != _metadata(os.fstat(descriptor)) or _metadata(frozen) != _metadata(named):
            _fail("changed")
        return digest, original_pin
    except NativeRSIRejectionError:
        raise
    except Exception as exc:
        raise NativeRSIRejectionError("write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()


__all__ = [
    "MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES", "NATIVE_RSI_REJECTION_PROVENANCE_NAME",
    "NativeRSIRejectionError", "NativeRSIRejectionEvidence", "NativeRSIRejectionFilePin",
    "RejectionLineageC1Binding", "map_native_rejection_to_solver_result",
    "persist_native_rsi_rejection_provenance", "read_native_rsi_rejection_provenance",
]
