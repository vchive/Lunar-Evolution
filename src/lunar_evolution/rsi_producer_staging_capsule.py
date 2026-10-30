"""Create-only, independently pinned full-ready evidence for opted-in RSI runs.

The reference is evidence only.  Its owner must retain the original staging permit,
checkpoint CAS and immutable mode; this module cannot reconstruct those authorities.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from itertools import chain
from pathlib import Path, PosixPath
from typing import NoReturn

from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import CandidateEvaluationError, canonical_json, strict_json
from .candidate_workspace_plan import CandidateWorkspaceError
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    LineageSnapshotPin,
    ProducerBundleLineageError,
    _observe_file,
    lineage_directory,
    persist_lineage_bytes_snapshot,
)
from .rsi_learning import RSILearningError

READY_CAPSULE_PROTOCOL = "lunar-rsi-producer-ready-capsule-v1"
MAX_READY_CAPSULE_BYTES = 64 * 1024
MAX_READY_CAPSULE_REFERENCE_BYTES = 8 * 1024
MAX_READY_BINDING_BYTES = 32 * 1024
READY_CAPSULE_FILENAME = "rsi-ready.snapshot"
_REFERENCE_FIELDS = frozenset({"protocol", "workspace", "journal_id", "workspace_identity", "file_pin"})
_READY_FIELDS = frozenset({"binding", "producer_checkpoint", "plan", "inputs", "input_manifest"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _fail(suffix: str) -> NoReturn:
    raise RSILearningError("rsi_producer_ready_capsule_" + suffix)


def _shape(value: object, *, depth: int = 0, remaining: list[int] | None = None) -> None:
    """Reject callbacks/subclasses before serializers, paths or dictionary lookup."""
    if remaining is None:
        remaining = [100_000]
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 48:
        _fail("shape_invalid")
    kind = type(value)
    if kind is dict:
        if len(value) > 10_000 or any(type(key) is not str for key in value):
            _fail("shape_invalid")
        items = chain.from_iterable(value.items())
    elif kind is list:
        if len(value) > 10_000:
            _fail("shape_invalid")
        items = value
    else:
        if kind is str:
            if len(value) > 128 * 1024:
                _fail("shape_invalid")
        elif kind is int:
            if value.bit_length() > 4096:
                _fail("shape_invalid")
        elif kind is float:
            if not math.isfinite(value):
                _fail("shape_invalid")
        elif value is not None and kind is not bool:
            _fail("shape_invalid")
        return
    for item in items:
        child_depth = depth + 1
        child_kind = type(item)
        if child_kind is dict or child_kind is list:
            _shape(item, depth=child_depth, remaining=remaining)
            continue
        # Keep each key/value occurrence's node and depth checks fresh while
        # avoiding a recursive Python call for exact scalar leaves.
        remaining[0] -= 1
        if remaining[0] < 0 or child_depth > 48:
            _fail("shape_invalid")
        if child_kind is str:
            if len(item) > 128 * 1024:
                _fail("shape_invalid")
        elif child_kind is int:
            if item.bit_length() > 4096:
                _fail("shape_invalid")
        elif child_kind is float:
            if not math.isfinite(item):
                _fail("shape_invalid")
        elif item is not None and child_kind is not bool:
            _fail("shape_invalid")


def _encode(value: object, maximum: int, suffix: str) -> bytes:
    try:
        return canonical_json(value, maximum=maximum)
    except CandidateEvaluationError as exc:
        raise RSILearningError("rsi_producer_ready_capsule_" + suffix) from exc


def _path(value: object) -> Path:
    if type(value) not in {str, Path, PosixPath}:
        _fail("workspace_invalid")
    wire = value if type(value) is str else str(value)
    try:
        if (not wire or "\x00" in wire or len(wire.encode("utf-8")) > 4096
                or not os.path.isabs(wire) or os.path.normpath(wire) != wire):
            _fail("workspace_invalid")
        path = Path(wire)
        if str(path) != wire:
            _fail("workspace_invalid")
        return path
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, RSILearningError):
            raise
        raise RSILearningError("rsi_producer_ready_capsule_workspace_invalid") from exc


def _journal(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail("journal_id_invalid")
    return value


def _full(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _READY_FIELDS:
        _fail("ready_invalid")
    if any(type(item) is not dict for item in value.values()):
        _fail("ready_invalid")
    return value


def _workspace_identity(value: object) -> dict[str, object]:
    if (type(value) is not dict or set(value) != {"device", "inode"}
            or any(type(item) is not int or not 0 <= item <= 2**64 - 1 for item in value.values())
            or value["inode"] == 0):
        _fail("workspace_identity_invalid")
    return value


def _association(ready: dict[str, object], workspace: Path, journal_id: str,
                 identity: dict[str, object] | None = None) -> dict[str, object]:
    inputs, plan, manifest = ready["inputs"], ready["plan"], ready["input_manifest"]
    if (inputs.get("workspace") != str(workspace)
            or inputs.get("journal_id") != journal_id or plan.get("journal_id") != journal_id
            or manifest.get("journal_id") != journal_id):
        _fail("association_invalid")
    original = _workspace_identity(manifest.get("workspace_identity"))
    if identity is not None and original != identity:
        _fail("association_invalid")
    return original


def _reference(value: object) -> tuple[dict[str, object], Path, str, LineageSnapshotPin]:
    _shape(value)
    if type(value) is not dict or set(value) != _REFERENCE_FIELDS:
        _fail("reference_invalid")
    if value["protocol"] != READY_CAPSULE_PROTOCOL:
        _fail("reference_invalid")
    workspace = _path(value["workspace"])
    journal_id = _journal(value["journal_id"])
    _workspace_identity(value["workspace_identity"])
    try:
        pin = LineageSnapshotPin.from_dict(value["file_pin"])
    except ProducerBundleLineageError as exc:
        raise RSILearningError("rsi_producer_ready_capsule_file_pin_invalid") from exc
    if pin.name != READY_CAPSULE_FILENAME or not 0 < pin.size <= MAX_READY_CAPSULE_BYTES:
        _fail("file_pin_invalid")
    _encode(value, MAX_READY_CAPSULE_REFERENCE_BYTES, "reference_too_large")
    return value, workspace, journal_id, pin


def _workspace_check(chain: DirectoryChain, original: dict[str, object]) -> None:
    chain.check()
    info = os.fstat(chain.fd)
    if {"device": info.st_dev, "inode": info.st_ino} != original:
        _fail("workspace_identity_drift")


def persist_ready_capsule(
    workspace: str | Path, journal_id: str, ready: object, *, retained_bytes: int = 0,
) -> dict[str, object]:
    """Create original canonical evidence once; never adopt any existing destination."""
    _shape(ready)
    full = _full(ready)
    root, journal_id = _path(workspace), _journal(journal_id)
    original_identity = _association(full, root, journal_id)
    if type(retained_bytes) is not int or not 0 <= retained_bytes <= MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("aggregate_exhausted")
    _encode(full["binding"], MAX_READY_BINDING_BYTES, "binding_too_large")
    raw = _encode(full, MAX_READY_CAPSULE_BYTES, "ready_too_large")
    if retained_bytes + len(raw) > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("aggregate_exhausted")
    chain = None
    try:
        chain = DirectoryChain(root, "rsi_producer_ready_capsule_workspace_invalid")
        identity = dict(original_identity)
        _workspace_check(chain, identity)
        path, pin = persist_lineage_bytes_snapshot(
            root, journal_id, name="rsi-ready", raw=raw,
            expected_sha256=hashlib.sha256(raw).hexdigest(), retained_bytes=retained_bytes,
        )
        _workspace_check(chain, identity)
        _observe_file(path, name=READY_CAPSULE_FILENAME, maximum=MAX_READY_CAPSULE_BYTES, expected_pin=pin)
        _workspace_check(chain, identity)
        reference = {"protocol": READY_CAPSULE_PROTOCOL, "workspace": str(root), "journal_id": journal_id,
                     "workspace_identity": identity, "file_pin": pin.to_dict()}
        _reference(reference)
        return reference
    except (ProducerBundleLineageError, CandidateWorkspaceError, OSError) as exc:
        raise RSILearningError("rsi_producer_ready_capsule_persist_failed") from exc
    finally:
        if chain is not None:
            chain.close()


def materialize_ready(
    ready: object, *, allow_capsule: bool = False,
    expected_workspace: str | Path | None = None, expected_journal_id: str | None = None,
) -> dict[str, object]:
    """Expand original pinned evidence read-only, or retain the ordinary full-ready path."""
    _shape(ready)
    if type(allow_capsule) is not bool:
        _fail("mode_invalid")
    expected_root = None if expected_workspace is None else _path(expected_workspace)
    expected_journal = None if expected_journal_id is None else _journal(expected_journal_id)
    if type(ready) is dict and set(ready) == _READY_FIELDS:
        return _full(ready)
    reference, root, journal_id, pin = _reference(ready)
    if not allow_capsule:
        _fail("mode_required")
    if expected_root is not None and expected_root != root:
        _fail("association_invalid")
    if expected_journal is not None and expected_journal != journal_id:
        _fail("association_invalid")
    chain = None
    try:
        chain = DirectoryChain(root, "rsi_producer_ready_capsule_workspace_invalid")
        _workspace_check(chain, reference["workspace_identity"])
        path = lineage_directory(root, journal_id) / READY_CAPSULE_FILENAME
        raw, _ = _observe_file(path, name=READY_CAPSULE_FILENAME, maximum=MAX_READY_CAPSULE_BYTES,
                               expected_pin=pin)
        _workspace_check(chain, reference["workspace_identity"])
        full = strict_json(raw, maximum=MAX_READY_CAPSULE_BYTES)
        _shape(full)
        full = _full(full)
        _encode(full["binding"], MAX_READY_BINDING_BYTES, "binding_too_large")
        if _encode(full, MAX_READY_CAPSULE_BYTES, "ready_too_large") != raw:
            _fail("canonical_invalid")
        _association(full, root, journal_id, reference["workspace_identity"])
        # Parsing is a separate boundary: do not refresh the original independently retained pin.
        _observe_file(path, name=READY_CAPSULE_FILENAME, maximum=MAX_READY_CAPSULE_BYTES,
                      expected_pin=pin)
        _workspace_check(chain, reference["workspace_identity"])
        return full
    except (ProducerBundleLineageError, CandidateWorkspaceError, CandidateEvaluationError, OSError) as exc:
        raise RSILearningError("rsi_producer_ready_capsule_read_failed") from exc
    finally:
        if chain is not None:
            chain.close()


def retained_ready_capsule_bytes(state: object) -> int:
    """Pure accounting over retained original references; never observe disk or adopt pins."""
    _shape(state)
    if type(state) is not dict:
        _fail("state_invalid")
    entries = state.get("producer_episode_staging", {})
    if type(entries) is not dict:
        _fail("state_invalid")
    total = 0
    for entry in entries.values():
        if type(entry) is not dict:
            _fail("state_invalid")
        ready = entry.get("ready")
        if ready is None:
            continue
        if type(ready) is dict and set(ready) == _READY_FIELDS:
            _full(ready)
            continue
        _, _, _, pin = _reference(ready)
        if state.get("producer_multi_episode_publication") is not True:
            _fail("mode_required")
        total += pin.size
        if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
            _fail("aggregate_exhausted")
    return total


def retained_publication_evidence_bytes(state: object) -> int:
    """Check the shared 64 MiB snapshot budget before any ready or lineage read."""
    total = retained_ready_capsule_bytes(state)
    wire = state.get("producer_publication_lineage")
    if wire is None:
        return total
    if state.get("producer_multi_episode_publication") is not True:
        _fail("mode_required")
    if (type(wire) is not dict or type(wire.get("batches")) is not list
            or len(wire["batches"]) > MAX_LINEAGE_BATCHES):
        _fail("state_invalid")
    v2 = wire.get("protocol") == "lunar-rsi-multi-episode-publication-v2"
    if v2 and state.get("producer_known_rejection") is not True:
        _fail("mode_required")
    for batch in wire["batches"]:
        if type(batch) is not dict or type(batch.get("snapshots")) is not dict:
            _fail("state_invalid")
        snapshots = batch["snapshots"]
        if not set(snapshots).issubset({"archive-before", "state-before", "archive-after", "state-after"}):
            _fail("file_pin_invalid")
        for name, raw_pin in snapshots.items():
            try:
                pin = LineageSnapshotPin.from_dict(raw_pin)
            except ProducerBundleLineageError as exc:
                raise RSILearningError("rsi_producer_ready_capsule_file_pin_invalid") from exc
            if pin.name != name + ".snapshot":
                _fail("file_pin_invalid")
            total += pin.size
            if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("aggregate_exhausted")
        if v2:
            from .rsi_native_rejection import NativeRSIRejectionFilePin

            for field, expected_name in (("before_file_pin", "before-v2.json"), ("staged_file_pin", "staged.json"),
                                          ("terminal_file_pin", "terminal.json"), ("rejected_file_pin", "rejected.json")):
                if field not in batch:
                    continue
                pin = LineageSnapshotPin.from_dict(batch[field])
                if pin.name != expected_name:
                    _fail("file_pin_invalid")
                total += pin.size
            evidence = batch.get("evidence_pins")
            if type(evidence) is not dict:
                _fail("state_invalid")
            for raw_pin in evidence.values():
                total += LineageSnapshotPin.from_dict(raw_pin).size
            reference = batch.get("rejection_provenance")
            if reference is not None:
                if type(reference) is not dict or set(reference) != {"provenance_sha256", "file_pin"}:
                    _fail("file_pin_invalid")
                total += NativeRSIRejectionFilePin.from_dict(reference["file_pin"]).size
            if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("aggregate_exhausted")
    return total
