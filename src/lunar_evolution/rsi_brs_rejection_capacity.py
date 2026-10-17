"""Pure first-ordinal BRS C1 material accounting; never owner authority."""

from __future__ import annotations

import hashlib
import re
from typing import Any, NoReturn

from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
)
from .producer_bundle_receipts import _validate_retained_evidence
from .rsi_learning import RSILearningError
from .rsi_native_rejection import MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
from .rsi_producer_staging_capsule import (
    READY_CAPSULE_PROTOCOL,
    _shape,
    retained_ready_capsule_bytes,
)

_BRS_PROTOCOL = "lunar-rsi-brs-lineage-checkpoint-v1"
_REJECTION_SCHEMA = "lunar-rsi-brs-rejection-c1-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_INT = 2**64 - 1
_OBSERVATION_FIELDS = (
    "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns",
    "mode", "nlink", "parent_device", "parent_inode",
)


def _fail(code: str) -> NoReturn:
    raise RSILearningError("rsi_brs_rejection_capacity_" + code)


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail("shape_invalid")
    return value


def _pin_record(raw: object, *, name: str) -> dict[str, Any]:
    pin = LineageSnapshotPin.from_dict(raw)
    if pin.name != name:
        _fail("pin_name_invalid")
    return {"kind": "file", **{field: getattr(pin, field) for field in _OBSERVATION_FIELDS}}


def _add_material(
    materials: dict[str, dict[str, Any]], identities: dict[tuple[int, int], str],
    path: str, record: dict[str, Any],
) -> int:
    """Deduplicate only one path with matching complete comparable observations."""
    for field in ("device", "inode", "mtime_ns", "ctime_ns"):
        value = record[field]
        if type(value) is not int or not 0 <= value <= _MAX_INT or (field == "inode" and value == 0):
            _fail("material_invalid")
    identity = (record["device"], record["inode"])
    previous_path = identities.get(identity)
    if previous_path is not None and previous_path != path:
        _fail("material_alias")
    previous = materials.get(path)
    if previous is not None:
        if any(previous[field] != record[field] for field in previous.keys() & record.keys()):
            _fail("material_drift")
        previous.update(record)
        return 0
    materials[path] = dict(record)
    identities[identity] = path
    return record["size"] if record["kind"] == "file" else 0


def retained_brs_c1_evidence_bytes(state: object, wire: object, retained_tables: object) -> int:
    """Count retained bytes, enforcing the unchanged 64 MiB bound plus future P.

    ``retained_tables`` is an insertion-ordered plain mapping from each rejected
    candidate ID to its complete native ``retained_evidence`` table. The original
    owner must independently reconstruct/verify those tables against the actual
    original pinned rejection files before and after this calculation. Parsing
    or counting a caller-created table does not grant any authority.

    The return value excludes the fixed future provenance reservation. It counts
    directories as zero bytes while still checking their identities, and counts
    zero-byte regular files without repacking their native modes as snapshot pins.
    No disk observation, flag rewriting, owner callback or checkpoint write occurs.
    """
    _shape(state)
    _shape(wire)
    _shape(retained_tables)
    # Preserve the existing capsule mode/shape/aggregate gates on the original
    # state. In particular, a BRS caller cannot manufacture DRS flags for a capsule.
    retained_ready_capsule_bytes(state)
    if type(state) is not dict or type(wire) is not dict or type(retained_tables) is not dict:
        _fail("shape_invalid")
    if (wire.get("protocol") != _BRS_PROTOCOL or wire.get("head") is not None
            or type(wire.get("batches")) is not list or len(wire["batches"]) != 1):
        _fail("shape_invalid")
    entry = wire["batches"][0]
    if (type(entry) is not dict or entry.get("state") != "rejected"
            or type(entry.get("ordinal")) is not int or entry["ordinal"] != 0
            or entry.get("rejection_schema") != _REJECTION_SCHEMA
            or entry.get("rejection_provenance") is not None
            or type(entry.get("rejected")) is not dict):
        _fail("shape_invalid")
    journal_id = _identifier(entry.get("journal_id"))
    candidate_ids = entry["rejected"].get("candidate_ids")
    if (type(candidate_ids) is not list or not 1 <= len(candidate_ids) <= 32
            or any(type(candidate_id) is not str for candidate_id in candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)):
        _fail("shape_invalid")
    for candidate_id in candidate_ids:
        _identifier(candidate_id)
    if any(type(key) is not str for key in retained_tables) or tuple(retained_tables) != tuple(candidate_ids):
        _fail("candidate_tables_invalid")
    snapshots, evidence = entry.get("snapshots"), entry.get("evidence_pins")
    evidence_names = (
        "journal.prepared.json", "journal.json", "rejections.json",
        *("rejections/" + candidate_id + ".json" for candidate_id in candidate_ids),
    )
    if (type(snapshots) is not dict or set(snapshots) != {"archive-before", "state-before"}
            or type(evidence) is not dict or set(evidence) != set(evidence_names)):
        _fail("pin_domain_invalid")
    workspace = wire.get("workspace")
    if type(workspace) is not dict or type(workspace.get("path")) is not str:
        _fail("shape_invalid")
    materials: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[int, int], str] = {}
    total = 0
    for staging in state.get("producer_episode_staging", {}).values():
        ready = staging.get("ready")
        if type(ready) is not dict or ready.get("protocol") != READY_CAPSULE_PROTOCOL:
            continue
        if ready["workspace"] != workspace["path"]:
            _fail("ready_domain_invalid")
        ready_journal = _identifier(ready["journal_id"])
        path = "evolution/producer-batches/" + ready_journal + "/lineage/rsi-ready.snapshot"
        total += _add_material(materials, identities, path,
                               _pin_record(ready["file_pin"], name="rsi-ready.snapshot"))
    prefix = "evolution/producer-batches/" + journal_id + "/"
    for name, raw in snapshots.items():
        filename = name + ".snapshot"
        total += _add_material(materials, identities, prefix + "lineage/" + filename,
                               _pin_record(raw, name=filename))
    for field, filename in (("before_file_pin", "before.json"), ("rejected_file_pin", "rejected.json")):
        total += _add_material(materials, identities, prefix + "lineage/" + filename,
                               _pin_record(entry.get(field), name=filename))
    for name in evidence_names:
        pin_name = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
        total += _add_material(materials, identities, prefix + name, _pin_record(evidence[name], name=pin_name))
    for table in retained_tables.values():
        _shape(table)
        clean = _validate_retained_evidence(table)
        for observation in clean["entries"]:
            path = observation["path"]
            record = {key: value for key, value in observation.items() if key != "path"}
            total += _add_material(materials, identities, path, record)
            if total + MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("aggregate_exhausted")
    if total + MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("aggregate_exhausted")
    return total


__all__ = ["retained_brs_c1_evidence_bytes"]
