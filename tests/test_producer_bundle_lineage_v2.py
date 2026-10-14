"""Pure/filesystem v2 contracts; no owner, producer or evaluator is executed."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

import pytest

from lunar_evolution import producer_bundle_lineage_v2 as v2
from lunar_evolution.producer_bundle_lineage import (
    LineageSnapshotPin,
    ProducerBundleLineageError,
    parse_lineage_descriptor,
)
from lunar_evolution.producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
    parse_lineage_v2_descriptor,
    persist_lineage_v2_descriptor,
    read_lineage_v2_descriptor_pinned,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _pin(name: str) -> LineageSnapshotPin:
    return LineageSnapshotPin(name=name, sha256=_sha(name), size=1, device=1, inode=2,
                              parent_device=1, parent_inode=3)


def _before(ordinal=0, outcome=None, published=False):
    return ProducerLineageBeforeIntentV2(
        run_id="run-1", journal_id=f"batch-{ordinal}", ordinal=ordinal,
        previous_attempt_journal_id=None if not ordinal else f"batch-{ordinal - 1}",
        previous_attempt_outcome=outcome,
        previous_attempt_terminal_sha256=None if not ordinal else _sha("previous-terminal"),
        previous_attempt_lineage_sha256=None if not ordinal else _sha("previous-lineage"),
        published_predecessor_journal_id=(f"batch-{ordinal - 1}" if outcome == "published" else "published-batch") if published else None,
        published_predecessor_terminal_sha256=_sha("previous-terminal") if published else None,
        published_predecessor_lineage_sha256=_sha("previous-lineage") if published else None,
        archive=_pin("archive-before.snapshot"), state=_pin("state-before.snapshot"),
    )


def _rejected():
    return ProducerLineageRejectedTerminalV2(
        run_id="run-1", journal_id="batch-0", episode_id="episode-1", ordinal=0,
        before_sha256=_before().digest(), prepared_journal_sha256=_sha("prepared"),
        terminal_journal_sha256=_sha("terminal"), rejection_manifest_sha256=_sha("raw pretty manifest"),
        terminal_marker_sha256=_sha("canonical manifest body"), candidate_ids=("candidate-1", "candidate-2"),
        archive_sha256=_sha("archive"), state_sha256=_sha("state"),
    )


@pytest.mark.parametrize("descriptor", [_before(), _before(1, "all_rejected"), _before(2, "all_rejected", True), _before(1, "published", True), _rejected()])
def test_canonical_roundtrip_detached_serialization_and_v1_refusal(descriptor):
    assert parse_lineage_v2_descriptor(descriptor.to_dict()) == descriptor
    assert parse_lineage_v2_descriptor(descriptor.to_json()) == descriptor
    assert parse_lineage_v2_descriptor(descriptor.to_json().decode()) == descriptor
    value = descriptor.to_dict()
    if isinstance(descriptor, ProducerLineageBeforeIntentV2):
        value["archive"]["sha256"] = _sha("changed")
    else:
        value["candidate_ids"].reverse()
    assert parse_lineage_v2_descriptor(descriptor.to_json()) == descriptor
    with pytest.raises(ProducerBundleLineageError, match="descriptor_digest_mismatch"):
        parse_lineage_v2_descriptor(value)
    with pytest.raises(ProducerBundleLineageError, match="kind_invalid"):
        parse_lineage_descriptor(descriptor.to_json())


@pytest.mark.parametrize("change", [
    {"previous_attempt_journal_id": "batch-1"},
    {"published_predecessor_journal_id": "batch-1"},
    {"previous_attempt_outcome": "published"},
    {"ordinal": 1}, {"ordinal": True}, {"ordinal": 8},
    {"archive": _pin("archive-before")}, {"state": _pin("state-before")},
])
def test_genesis_strict_association_and_snapshot_names(change):
    with pytest.raises(ProducerBundleLineageError):
        replace(_before(), **change, descriptor_sha256=None)


@pytest.mark.parametrize("change", [
    {"previous_attempt_journal_id": None}, {"previous_attempt_outcome": None},
    {"previous_attempt_terminal_sha256": None}, {"previous_attempt_lineage_sha256": None},
    {"previous_attempt_outcome": "rejected"}, {"previous_attempt_outcome": True},
    {"previous_attempt_journal_id": "batch-1"},
    {"published_predecessor_journal_id": "batch-1", "published_predecessor_terminal_sha256": _sha("p"), "published_predecessor_lineage_sha256": _sha("q")},
    {"published_predecessor_journal_id": "batch-0", "published_predecessor_terminal_sha256": _sha("p"), "published_predecessor_lineage_sha256": _sha("q")},
    {"published_predecessor_terminal_sha256": _sha("p")},
])
def test_rejected_predecessor_group_is_complete_and_not_published(change):
    with pytest.raises(ProducerBundleLineageError):
        replace(_before(1, "all_rejected"), **change, descriptor_sha256=None)


@pytest.mark.parametrize("change", [
    {"published_predecessor_journal_id": "another-batch"},
    {"published_predecessor_terminal_sha256": _sha("other-terminal")},
    {"published_predecessor_lineage_sha256": _sha("other-lineage")},
    {"published_predecessor_journal_id": None, "published_predecessor_terminal_sha256": None, "published_predecessor_lineage_sha256": None},
])
def test_previous_published_requires_complete_identical_published_association(change):
    with pytest.raises(ProducerBundleLineageError):
        replace(_before(1, "published", True), **change, descriptor_sha256=None)


@pytest.mark.parametrize("ids", [(), ("a", "a"), ["a"], ("../a",), (True,), tuple(f"c-{index}" for index in range(33))])
def test_rejected_candidate_tuple_bounded_unique_and_ordered(ids):
    with pytest.raises(ProducerBundleLineageError):
        replace(_rejected(), candidate_ids=ids, descriptor_sha256=None)


def test_raw_manifest_and_terminal_body_marker_have_distinct_fields():
    descriptor = _rejected()
    assert descriptor.rejection_manifest_sha256 != descriptor.terminal_marker_sha256
    wire = descriptor.to_dict()
    wire["rejection_manifest_sha256"], wire["terminal_marker_sha256"] = wire["terminal_marker_sha256"], wire["rejection_manifest_sha256"]
    with pytest.raises(ProducerBundleLineageError, match="descriptor_digest_mismatch"):
        parse_lineage_v2_descriptor(wire)


@pytest.mark.parametrize("factory,field,value", [
    (_before, "ordinal", True), (_before, "protocol", "v1"), (_before, "descriptor_sha256", None),
    (_rejected, "candidate_ids", ["candidate-1"]), (_rejected, "archive_sha256", "bad"),
    (_rejected, "descriptor_sha256", None), (_rejected, "episode_id", "../episode"),
])
@pytest.mark.parametrize("method", ["to_dict", "to_json", "digest"])
def test_mutated_exact_dto_is_revalidated(factory, field, value, method):
    descriptor = factory()
    object.__setattr__(descriptor, field, value)
    with pytest.raises(ProducerBundleLineageError):
        getattr(descriptor, method)()


@pytest.mark.parametrize("field,value", [("mode", 0o400), ("inode", True), ("name", "other"), ("sha256", "bad")])
def test_mutated_exact_nested_pin_is_revalidated_before_creation(tmp_path, field, value):
    descriptor = _before()
    object.__setattr__(descriptor.archive, field, value)
    with pytest.raises(ProducerBundleLineageError):
        persist_lineage_v2_descriptor(tmp_path, descriptor)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("descriptor", [_before(), _rejected()])
def test_create_only_original_file_pin_and_fixed_pinned_reader(tmp_path, descriptor):
    (tmp_path / "evolution/producer-batches/batch-0").mkdir(parents=True)
    path, pin = persist_lineage_v2_descriptor(tmp_path, descriptor)
    assert path.name == f"{descriptor.kind}.json"
    assert pin.mode == 0o600 and pin.sha256 == hashlib.sha256(descriptor.to_json()).hexdigest()
    assert read_lineage_v2_descriptor_pinned(tmp_path, "batch-0", kind=descriptor.kind, expected_file_pin=pin) == descriptor
    assert persist_lineage_v2_descriptor(tmp_path, descriptor, expected_file_pin=pin) == (path, pin)
    with pytest.raises(ProducerBundleLineageError, match="original_file_pin_required"):
        persist_lineage_v2_descriptor(tmp_path, descriptor)


@pytest.mark.parametrize("mutation", ["replace", "touch", "symlink", "hardlink", "mode"])
def test_pinned_reader_refuses_inode_stat_permission_or_link_drift(tmp_path, mutation):
    (tmp_path / "evolution/producer-batches/batch-0").mkdir(parents=True)
    descriptor = _rejected()
    path, pin = persist_lineage_v2_descriptor(tmp_path, descriptor)
    if mutation == "replace":
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
    elif mutation == "touch":
        os.utime(path, ns=(pin.mtime_ns + 1, pin.mtime_ns + 1))
    elif mutation == "symlink":
        path.unlink()
        path.symlink_to("missing")
    elif mutation == "hardlink":
        os.link(path, path.with_name("alias"))
    else:
        path.chmod(0o400)
    with pytest.raises(ProducerBundleLineageError):
        read_lineage_v2_descriptor_pinned(tmp_path, "batch-0", kind="rejected", expected_file_pin=pin)


@pytest.mark.parametrize("value", [None, True, {"kind": "unknown"}, {"kind": "rejected", "extra": 1}])
def test_parser_refuses_invalid_types_and_shape(value):
    with pytest.raises(ProducerBundleLineageError):
        parse_lineage_v2_descriptor(value)


@pytest.mark.parametrize("transform", [lambda raw: raw + b"\n", lambda raw: json.dumps(json.loads(raw), indent=2).encode(), lambda raw: raw.replace(b'"ordinal":0', b'"ordinal":0,"ordinal":0')])
def test_parser_refuses_noncanonical_and_duplicate_keys(transform):
    with pytest.raises(ProducerBundleLineageError):
        parse_lineage_v2_descriptor(transform(_before().to_json()))


def test_callbacks_are_refused_before_filesystem_or_serialization(tmp_path):
    class Trap:
        def __fspath__(self):
            pytest.fail("path callback")

        def to_dict(self):
            pytest.fail("DTO callback")

    for value in (Trap(), {"kind": Trap()}):
        with pytest.raises(ProducerBundleLineageError):
            parse_lineage_v2_descriptor(value)
    with pytest.raises(ProducerBundleLineageError):
        persist_lineage_v2_descriptor(tmp_path, Trap())
    descriptor = _before()
    object.__setattr__(descriptor, "archive", Trap())
    with pytest.raises(ProducerBundleLineageError):
        persist_lineage_v2_descriptor(tmp_path, descriptor)
    assert list(tmp_path.iterdir()) == []


def test_invalid_descriptor_cap_refuses_before_any_create(tmp_path):
    with pytest.raises(ProducerBundleLineageError, match="descriptor_too_large"):
        v2._canonical({"value": "a" * (32 * 1024)})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("dto", [ProducerLineageBeforeIntentV2, ProducerLineageRejectedTerminalV2])
def test_direct_wire_shape_precedes_colliding_subclass_key_equality(dto):
    callbacks = []

    class Key(str):
        def __hash__(self):
            return 7

        def __eq__(self, other):
            callbacks.append("eq")
            return str.__eq__(self, other)

    value = {Key("kind"): "rejected", Key("extra"): "refused"}
    callbacks.clear()
    with pytest.raises(ProducerBundleLineageError, match="schema_invalid"):
        dto.from_dict(value)
    assert callbacks == []


@pytest.mark.parametrize("boundary", ["before", "reader", "writer"])
def test_pin_shape_precedes_nlink_comparison_and_filesystem_io(tmp_path, monkeypatch, boundary):
    callbacks = []

    class Count:
        def __ne__(self, _other):
            callbacks.append("ne")
            return True

    pin = _pin("archive-before.snapshot" if boundary == "before" else "before-v2.json")
    object.__setattr__(pin, "nlink", Count())

    def forbidden(*_args, **_kwargs):
        pytest.fail("malformed pin must be refused before filesystem I/O")

    monkeypatch.setattr(v2, "_create_lineage_file", forbidden)
    monkeypatch.setattr(v2, "_observe_file", forbidden)
    monkeypatch.setattr(v2, "lineage_directory", forbidden)
    with pytest.raises(ProducerBundleLineageError, match="schema_invalid"):
        if boundary == "before":
            replace(_before(), archive=pin, descriptor_sha256=None)
        elif boundary == "reader":
            read_lineage_v2_descriptor_pinned(tmp_path, "batch-0", kind="before-v2", expected_file_pin=pin)
        else:
            persist_lineage_v2_descriptor(tmp_path, _before(), expected_file_pin=pin)
    assert callbacks == [] and list(tmp_path.iterdir()) == []
