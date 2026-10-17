"""Pure capacity checks use detached material only and grant no owner authority."""

from __future__ import annotations

from copy import deepcopy

import pytest

from lunar_evolution import rsi_brs_rejection_capacity as capacity
from lunar_evolution import rsi_producer_staging_capsule as capsule
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
)
from lunar_evolution.producer_bundle_receipts import _retained_evidence_digest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_rejection import MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES


def _pin(name, inode, size=3):
    return LineageSnapshotPin(name, "a" * 64, size, 1, inode, 1, 1000,
                              mtime_ns=10, ctime_ns=11).to_dict()


def _table(entries):
    value = {"schema_version": "1", "protocol": "lunar-native-retained-evidence-v1",
             "entries": sorted(entries, key=lambda item: item["path"])}
    value["evidence_sha256"] = _retained_evidence_digest(value)
    return value


def _file(path, inode, size=7):
    return {"path": path, "kind": "file", "size": size, "sha256": "a" * 64,
            "device": 1, "inode": inode, "mtime_ns": 10, "ctime_ns": 11}


def _fixture(ids=("c1",)):
    evidence = {"journal.prepared.json": _pin("journal.prepared.json", 11, 5),
                "journal.json": _pin("journal.json", 12),
                "rejections.json": _pin("rejections.json", 13)}
    for index, candidate_id in enumerate(ids):
        name = "rejections/" + candidate_id + ".json"
        pin_name = "rejection-" + capacity.hashlib.sha256(name.encode()).hexdigest()
        evidence[name] = _pin(pin_name, 20 + index)
    wire = {"protocol": "lunar-rsi-brs-lineage-checkpoint-v1", "head": None,
            "workspace": {"path": "/fixture"}, "batches": [{
                "state": "rejected", "ordinal": 0, "journal_id": "j1",
                "rejection_schema": "lunar-rsi-brs-rejection-c1-v1", "rejection_provenance": None,
                "rejected": {"candidate_ids": list(ids)},
                "snapshots": {"archive-before": _pin("archive-before.snapshot", 1, 9),
                              "state-before": _pin("state-before.snapshot", 2, 11)},
                "before_file_pin": _pin("before.json", 3),
                "rejected_file_pin": _pin("rejected.json", 4), "evidence_pins": evidence,
            }]}
    tables = {}
    for index, candidate_id in enumerate(ids):
        shared = _file("evolution/producer-batches/j1/journal.prepared.json", 11, 5)
        directory = {"path": "evolution/bundle-attempts", "kind": "directory", "size": None,
                     "sha256": None, "device": 1, "inode": 99, "mtime_ns": 10, "ctime_ns": 11}
        tables[candidate_id] = _table([
            shared, directory, _file("evolution/native/" + candidate_id + "/output", 100 + index),
            _file("evolution/native/" + candidate_id + "/empty", 200 + index, 0),
        ])
    return {}, wire, tables


def _actual_without_tables(wire):
    entry = wire["batches"][0]
    return (sum(pin["size"] for pin in entry["snapshots"].values())
            + entry["before_file_pin"]["size"] + entry["rejected_file_pin"]["size"]
            + sum(pin["size"] for pin in entry["evidence_pins"].values()))


@pytest.mark.parametrize("ids", [("c1",), ("c1", "c2")])
def test_counts_full_material_once_with_shared_prepared_directories_and_empty_files(ids, monkeypatch):
    state, wire, tables = _fixture(ids)
    monkeypatch.setattr("pathlib.Path.stat", lambda *_args, **_kwargs: pytest.fail("pure kernel read disk"))
    monkeypatch.setattr("pathlib.Path.lstat", lambda *_args, **_kwargs: pytest.fail("pure kernel read disk"))
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: pytest.fail("pure kernel read disk"))
    original = deepcopy((state, wire, tables))
    assert capacity.retained_brs_c1_evidence_bytes(state, wire, tables) == _actual_without_tables(wire) + 7 * len(ids)
    assert (state, wire, tables) == original


def test_exact_aggregate_plus_future_p_boundary_and_one_byte_over():
    state, wire, tables = _fixture()
    remaining = (MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
                 - _actual_without_tables(wire) - 7)
    extra = []
    while remaining:
        size = min(remaining, MAX_LINEAGE_SNAPSHOT_BYTES)
        extra.append(_file("evolution/large/" + str(len(extra)), 500 + len(extra), size))
        remaining -= size
    tables["c1"] = _table(tables["c1"]["entries"] + extra)
    actual = capacity.retained_brs_c1_evidence_bytes(state, wire, tables)
    assert actual == MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES
    extra[-1]["size"] += 1
    tables["c1"] = _table([item for item in tables["c1"]["entries"] if not item["path"].startswith("evolution/large/")] + extra)
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        capacity.retained_brs_c1_evidence_bytes(state, wire, tables)


@pytest.mark.parametrize("field", ["size", "sha256", "device", "inode", "mtime_ns", "ctime_ns"])
def test_same_prepared_path_with_changed_comparable_pin_is_drift(field):
    state, wire, tables = _fixture()
    shared = next(item for item in tables["c1"]["entries"] if item["path"].endswith("journal.prepared.json"))
    shared[field] = "b" * 64 if field == "sha256" else shared[field] + 10000
    tables["c1"] = _table(tables["c1"]["entries"])
    with pytest.raises(RSILearningError, match="material_drift"):
        capacity.retained_brs_c1_evidence_bytes(state, wire, tables)


@pytest.mark.parametrize("domain", ["native", "descriptor", "directory"])
def test_distinct_paths_with_the_same_inode_are_refused(domain):
    state, wire, tables = _fixture()
    entries = tables["c1"]["entries"]
    if domain == "descriptor":
        wire["batches"][0]["rejected_file_pin"]["inode"] = 3
    else:
        original = next(item for item in entries if item["kind"] == ("directory" if domain == "directory" else "file"))
        alias = {**original, "path": "evolution/another-path"}
        tables["c1"] = _table([*entries, alias])
    with pytest.raises(RSILearningError, match="material_alias"):
        capacity.retained_brs_c1_evidence_bytes(state, wire, tables)


def test_original_capsule_flags_remain_required_and_valid_reference_is_counted_once():
    state, wire, tables = _fixture()
    reference = {"protocol": capsule.READY_CAPSULE_PROTOCOL, "workspace": "/fixture", "journal_id": "j1",
                 "workspace_identity": {"device": 1, "inode": 1000},
                 "file_pin": _pin("rsi-ready.snapshot", 77, 17)}
    state["producer_episode_staging"] = {"one": {"ready": reference}, "same": {"ready": deepcopy(reference)}}
    for flag in (None, False, 1, "true"):
        state["producer_multi_episode_publication"] = flag
        with pytest.raises(RSILearningError, match="mode_required"):
            capacity.retained_brs_c1_evidence_bytes(state, wire, tables)
    state["producer_multi_episode_publication"] = True
    assert capacity.retained_brs_c1_evidence_bytes(state, wire, tables) == _actual_without_tables(wire) + 7 + 17
    with pytest.raises(RSILearningError, match="mode_required"):
        capsule.retained_publication_evidence_bytes({"producer_publication_lineage": wire})


@pytest.mark.parametrize("mutation", ["order", "missing", "extra", "wrong_pin", "after", "provenance", "ordinal"])
def test_scope_and_material_domains_are_finite(mutation):
    state, wire, tables = _fixture(("c1", "c2"))
    entry = wire["batches"][0]
    if mutation == "order":
        tables = dict(reversed(tuple(tables.items())))
    elif mutation == "missing":
        tables.pop("c1")
    elif mutation == "extra":
        entry["evidence_pins"]["extra.json"] = _pin("extra.json", 80)
    elif mutation == "wrong_pin":
        entry["evidence_pins"]["rejections/c1.json"]["name"] = "wrong.json"
    elif mutation == "after":
        entry["snapshots"]["archive-after"] = _pin("archive-after.snapshot", 81)
    elif mutation == "provenance":
        entry["rejection_provenance"] = {"file_pin": {}}
    else:
        entry["ordinal"] = True
    with pytest.raises((RSILearningError, ValueError)):
        capacity.retained_brs_c1_evidence_bytes(state, wire, tables)


def test_subclass_callbacks_are_rejected_before_they_run():
    class Dangerous(dict):
        def items(self):
            pytest.fail("capacity invoked caller callback")

    state, wire, tables = _fixture()
    tables["c1"] = Dangerous(tables["c1"])
    with pytest.raises(RSILearningError, match="shape_invalid"):
        capacity.retained_brs_c1_evidence_bytes(state, wire, tables)


def test_candidate_key_subclass_is_rejected_before_tuple_equality():
    class DangerousString(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            pytest.fail("capacity invoked foreign key equality")

    state, wire, tables = _fixture()
    unsafe = {DangerousString("c1"): tables["c1"]}
    with pytest.raises(RSILearningError, match="shape_invalid"):
        capacity.retained_brs_c1_evidence_bytes(state, wire, unsafe)


def test_referenced_native_record_accepts_real_modes_without_snapshot_repacking():
    state, wire, tables = _fixture()
    # Native tables deliberately do not have LineageSnapshotPin mode/parent fields.
    assert all("mode" not in item for item in tables["c1"]["entries"])
    assert capacity.retained_brs_c1_evidence_bytes(state, wire, tables) == _actual_without_tables(wire) + 7
