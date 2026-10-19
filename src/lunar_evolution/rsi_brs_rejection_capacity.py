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
from .rsi_native_rejection import (
    MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES,
    NativeRSIRejectionFilePin,
)
from .rsi_producer_staging_capsule import (
    READY_CAPSULE_PROTOCOL,
    _shape,
    retained_ready_capsule_bytes,
)

_BRS_PROTOCOL = "lunar-rsi-brs-lineage-checkpoint-v1"
_REJECTION_SCHEMA = "lunar-rsi-brs-rejection-c1-v1"
_LINEAGE_FIELD = "producer_publication_lineage"
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
    total, _materials, _identities = _retained_brs_c1_materials(
        state, wire, retained_tables, provenance_reserve=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)
    return total


def _retained_brs_c1_materials(
    state: object, wire: object, retained_tables: object, *, provenance_reserve: int,
) -> tuple[int, dict[str, dict[str, Any]], dict[tuple[int, int], str]]:
    """Accumulate the finite C1 material domain for the two bounded kernels."""
    if type(provenance_reserve) is not int or provenance_reserve not in {
            0, MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES}:
        _fail("shape_invalid")
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
            if total + provenance_reserve > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("aggregate_exhausted")
    if total + provenance_reserve > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("aggregate_exhausted")
    return total, materials, identities


def retained_brs_c2_evidence_bytes(
    captured_c1_state: object, c2_wire: object, retained_tables: object,
) -> int:
    """Count original C1 material plus actual P under its native 0400 pin.

    The captured state must contain its original C1 wire. The pure transition
    check binds C2 to that wire; the original owner must still independently
    verify the captured state, unchanged native tables and held publishing pin.
    No future P reservation is added after counting the actual provenance file.
    """
    from .rsi_brs_rejection_c1 import validate_rejected_provenance_transition

    _shape(captured_c1_state)
    _shape(c2_wire)
    _shape(retained_tables)
    if type(captured_c1_state) is not dict:
        _fail("shape_invalid")
    c1_wire = captured_c1_state.get(_LINEAGE_FIELD)
    validate_rejected_provenance_transition(c1_wire, c2_wire)
    total, materials, identities = _retained_brs_c1_materials(
        captured_c1_state, c1_wire, retained_tables, provenance_reserve=0)
    entry = c2_wire["batches"][0]
    pin = NativeRSIRejectionFilePin.from_dict(entry["rejection_provenance"]["file_pin"])
    path = "evolution/producer-batches/" + entry["journal_id"] + "/" + pin.name
    if path in materials:
        _fail("provenance_domain_invalid")
    record = {"kind": "file", **{field: getattr(pin, field) for field in _OBSERVATION_FIELDS}}
    total += _add_material(materials, identities, path, record)
    if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("aggregate_exhausted")
    return total


def _retained_reserved_brs_materials(
    state, wire, retained_tables, published_tables, *, prefix, original_lineage_bytes,
    native_plan_sha256, provenance_reserve, with_provenance=False,
):
    """Count the complete immutable prefix and active native rejection material.

    These tables are observations supplied by the original owner's independent
    physical readers. A prefix or a counted table grants no publication authority.
    Unlike the legacy API, this private kernel explicitly receives the original
    whole-wire prefix; it never slices a multi-batch wire into a single batch.
    """
    from .rsi_brs_reserved_rejection import (
        _transition_scope,
        validate_reserved_brs_rejected_entry,
    )

    _shape(state)
    _shape(wire)
    _shape(retained_tables)
    _shape(published_tables)
    if (type(state) is not dict or type(wire) is not dict
            or type(retained_tables) is not dict or type(published_tables) is not dict
            or type(with_provenance) is not bool
            or type(provenance_reserve) is not int
            or provenance_reserve not in {0, MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES}):
        _fail("shape_invalid")
    retained_ready_capsule_bytes(state)
    _before, active, old_index = _transition_scope(wire, wire, prefix, original_lineage_bytes)
    rejected = validate_reserved_brs_rejected_entry(active, prefix=prefix,
        native_plan_sha256=native_plan_sha256, with_provenance=with_provenance)
    if wire["rejections"] != [*old_index, {"ordinal": rejected.ordinal,
            "journal_id": rejected.journal_id, "rejected_sha256": rejected.digest()}]:
        _fail("rejection_index_invalid")
    entries = wire["batches"]
    rejected_ids = tuple(entry["journal_id"] for entry in entries if entry["state"] == "rejected")
    published_ids = tuple(entry["journal_id"] for entry in entries if entry["state"] == "terminal")
    if (any(type(key) is not str for key in retained_tables)
            or tuple(retained_tables) != rejected_ids
            or any(type(key) is not str for key in published_tables)
            or tuple(published_tables) != published_ids):
        _fail("journal_tables_invalid")
    materials, identities = {}, {}
    total = 0
    workspace = wire["workspace"]["path"]
    for staging in state.get("producer_episode_staging", {}).values():
        ready = staging.get("ready")
        if type(ready) is not dict or ready.get("protocol") != READY_CAPSULE_PROTOCOL:
            continue
        if ready["workspace"] != workspace:
            _fail("ready_domain_invalid")
        path = "evolution/producer-batches/" + _identifier(ready["journal_id"]) + "/lineage/rsi-ready.snapshot"
        total += _add_material(materials, identities, path,
                               _pin_record(ready["file_pin"], name="rsi-ready.snapshot"))
    for entry in entries:
        journal = _identifier(entry["journal_id"])
        base = "evolution/producer-batches/" + journal + "/"
        for name, pin in entry["snapshots"].items():
            filename = name + ".snapshot"
            total += _add_material(materials, identities, base + "lineage/" + filename,
                                   _pin_record(pin, name=filename))
        for kind in ("before", "staged", "terminal", "rejected"):
            field = kind + "_file_pin"
            if field in entry:
                name = "before-v2.json" if kind == "before" and entry["ordinal"] else kind + ".json"
                total += _add_material(materials, identities, base + "lineage/" + name,
                                       _pin_record(entry[field], name=name))
        for name, pin in entry["evidence_pins"].items():
            pin_name = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
            total += _add_material(materials, identities, base + name, _pin_record(pin, name=pin_name))
        if entry["state"] == "rejected":
            tables = retained_tables[journal]
            candidate_ids = entry["rejected"]["candidate_ids"]
            if type(tables) is not dict or tuple(tables) != tuple(candidate_ids):
                _fail("candidate_tables_invalid")
            for table in tables.values():
                clean = _validate_retained_evidence(table)
                for observation in clean["entries"]:
                    total += _add_material(materials, identities, observation["path"],
                                           {key: value for key, value in observation.items() if key != "path"})
            reference = entry.get("rejection_provenance")
            if reference is not None:
                pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
                total += _add_material(materials, identities, base + pin.name,
                    {"kind": "file", **{field: getattr(pin, field) for field in _OBSERVATION_FIELDS}})
        else:
            table = published_tables[journal]
            required = {"kind", "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns"}
            optional = {"mode", "nlink", "parent_device", "parent_inode"}
            if (type(table) is not dict or not table or any(type(path) is not str for path in table)
                    or any(type(record) is not dict or not required <= set(record)
                           or not set(record) <= required | optional for record in table.values())):
                _fail("published_tables_invalid")
            for record in table.values():
                if any(type(record[field]) is not int or not 0 <= record[field] <= _MAX_INT
                       for field in optional & set(record)):
                    _fail("published_tables_invalid")
            # The native retained-evidence parser validates canonical paths,
            # numeric bounds and kinds without changing native file modes.
            observations = [{"path": path, **record} for path, record in table.items()]
            from .producer_bundle_receipts import _retained_evidence_digest
            document = {"schema_version": "1", "protocol": "lunar-native-retained-evidence-v1",
                        "entries": sorted(({key: item[key] for key in (
                            "path", "kind", "size", "sha256", "device", "inode", "mtime_ns", "ctime_ns")}
                            for item in observations), key=lambda item: item["path"])}
            document["evidence_sha256"] = _retained_evidence_digest(document)
            _validate_retained_evidence(document)
            for observation in observations:
                total += _add_material(materials, identities, observation["path"],
                                       {key: value for key, value in observation.items() if key != "path"})
        if total + provenance_reserve > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
            _fail("aggregate_exhausted")
    return total, materials, identities


def _retained_reserved_brs_c1_evidence_bytes(
    state, wire, retained_tables, published_tables, *, prefix, original_lineage_bytes, native_plan_sha256,
):
    return _retained_reserved_brs_materials(state, wire, retained_tables, published_tables,
        prefix=prefix, original_lineage_bytes=original_lineage_bytes, native_plan_sha256=native_plan_sha256,
        provenance_reserve=MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES)[0]


def _retained_reserved_brs_c2_evidence_bytes(
    captured_c1_state, c2_wire, retained_tables, published_tables, *, prefix, original_lineage_bytes,
    native_plan_sha256,
):
    from .rsi_brs_reserved_rejection import validate_reserved_brs_c2_transition

    _shape(captured_c1_state)
    if type(captured_c1_state) is not dict:
        _fail("shape_invalid")
    validate_reserved_brs_c2_transition(captured_c1_state.get(_LINEAGE_FIELD), c2_wire, prefix=prefix,
        original_lineage_bytes=original_lineage_bytes, native_plan_sha256=native_plan_sha256)
    return _retained_reserved_brs_materials(captured_c1_state, c2_wire, retained_tables, published_tables,
        prefix=prefix, original_lineage_bytes=original_lineage_bytes, native_plan_sha256=native_plan_sha256,
        provenance_reserve=0, with_provenance=True)[0]


__all__ = ["retained_brs_c1_evidence_bytes", "retained_brs_c2_evidence_bytes"]
