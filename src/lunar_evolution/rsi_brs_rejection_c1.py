"""Strict first-ordinal BRS rejection wire observations, without owner authority."""

from __future__ import annotations

import hashlib

from .producer_bundle_lineage import LineageSnapshotPin, ProducerLineageBeforeIntent
from .producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .rsi_learning import RSILearningError
from .rsi_python_admission import validate_rsi_python_admission_shapes

REJECTION_SCHEMA = "lunar-rsi-brs-rejection-c1-v1"

_BASE_FIELDS = frozenset({
    "journal_id", "ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256",
    "native_plan_sha256", "admission_plan", "prepared_journal", "before", "before_file_pin",
    "snapshots", "before_sources", "state", "evidence_pins",
})
_REJECTED_FIELDS = frozenset({
    "rejected", "rejected_file_pin", "rejected_journal", "rejection_provenance", "rejection_schema",
})


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_publication_lineage_rejected_" + reason)


def rejected_c1_entry(entry: object) -> ProducerLineageRejectedTerminalV2:
    """Validate this finite outcome variant; no disk lookup or owner reconstruction."""
    validate_rsi_python_admission_shapes(entry)
    if (type(entry) is not dict or set(entry) != _BASE_FIELDS | _REJECTED_FIELDS
            or entry.get("state") != "rejected" or entry.get("rejection_schema") != REJECTION_SCHEMA
            or entry.get("rejection_provenance") is not None
            or type(entry.get("ordinal")) is not int or entry["ordinal"] != 0
            or type(entry.get("snapshots")) is not dict
            or set(entry["snapshots"]) != {"archive-before", "state-before"}
            or type(entry.get("evidence_pins")) is not dict):
        _fail("shape_invalid")
    rejected = ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"])
    before = ProducerLineageBeforeIntent.from_dict(entry["before"])
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
    if (prepared.state != "prepared" or terminal.state != "all_rejected"
            or (rejected.run_id, rejected.journal_id, rejected.episode_id, rejected.ordinal) !=
                (prepared.run_id, entry["journal_id"], entry["episode_id"], 0)
            or terminal.run_id != rejected.run_id or terminal.journal_id != rejected.journal_id
            or prepared.journal_id != rejected.journal_id or before.run_id != rejected.run_id
            or before.journal_id != rejected.journal_id or before.ordinal != 0
            or before.predecessor_terminal_sha256 is not None or before.predecessor_lineage_sha256 is not None
            or rejected.before_sha256 != before.digest()
            or rejected.prepared_journal_sha256 != prepared.digest()
            or rejected.terminal_journal_sha256 != terminal.digest()
            or rejected.terminal_marker_sha256 != terminal.terminal_marker_sha256
            or rejected.candidate_ids != tuple(item.candidate_id for item in prepared.candidates)
            or rejected.candidate_ids != tuple(item.candidate_id for item in terminal.candidates)
            or (rejected.archive_sha256, rejected.state_sha256) != (before.archive.sha256, before.state.sha256)
            or (terminal.archive_after_sha256, terminal.state_after_sha256) !=
                (before.archive.sha256, before.state.sha256)):
        _fail("binding_invalid")
    if (before.archive.to_dict() != entry["snapshots"]["archive-before"]
            or before.state.to_dict() != entry["snapshots"]["state-before"]):
        _fail("snapshot_invalid")
    expected = {"journal.prepared.json", "journal.json", "rejections.json",
                *("rejections/" + item + ".json" for item in rejected.candidate_ids)}
    if set(entry["evidence_pins"]) != expected:
        _fail("pins_invalid")
    for name, raw in entry["snapshots"].items():
        if LineageSnapshotPin.from_dict(raw).name != name + ".snapshot":
            _fail("pins_invalid")
    for name, raw in entry["evidence_pins"].items():
        expected_name = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
        if LineageSnapshotPin.from_dict(raw).name != expected_name:
            _fail("pins_invalid")
    for kind, descriptor in (("before", before), ("rejected", rejected)):
        pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
        raw = descriptor.to_json()
        if pin.name != kind + ".json" or pin.size != len(raw) or pin.sha256 != hashlib.sha256(raw).hexdigest():
            _fail("descriptor_pin_invalid")
    return rejected


def rejected_c1_index(entry: object) -> list[dict[str, object]]:
    rejected = rejected_c1_entry(entry)
    return [{"ordinal": 0, "journal_id": rejected.journal_id, "rejected_sha256": rejected.digest()}]


def validate_rejected_c1_transition(previous: object, current: object) -> None:
    """Admit exactly the prepared-before to rejected wire delta."""
    validate_rsi_python_admission_shapes((previous, current))
    if (type(previous) is not dict or type(current) is not dict or set(previous) != set(current)
            or type(previous.get("batches")) is not list or len(previous["batches"]) != 1
            or type(current.get("batches")) is not list or len(current["batches"]) != 1
            or previous.get("head") is not None or current.get("head") is not None
            or previous.get("rejections") != []):
        _fail("delta_invalid")
    before, rejected = previous["batches"][0], current["batches"][0]
    rejected_c1_entry(rejected)
    if (type(before) is not dict or set(before) != _BASE_FIELDS or before.get("state") != "before"
            or type(before.get("evidence_pins")) is not dict
            or set(before["evidence_pins"]) != {"journal.prepared.json"}
            or current.get("rejections") != rejected_c1_index(rejected)):
        _fail("delta_invalid")
    for key, value in previous.items():
        if key not in {"batches", "rejections"} and current[key] != value:
            _fail("delta_invalid")
    for key, value in before.items():
        if key == "evidence_pins":
            if rejected[key].get("journal.prepared.json") != value["journal.prepared.json"]:
                _fail("delta_invalid")
        elif key != "state" and rejected.get(key) != value:
            _fail("delta_invalid")
