"""Pure and local create-only contracts for opt-in multi-episode lineage evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lunar_evolution import producer_bundle_lineage as lineage
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
    ProducerBundleLineageError,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    lineage_directory,
    parse_lineage_descriptor,
    persist_lineage_bytes_snapshot,
    persist_lineage_descriptor,
    persist_lineage_snapshot,
    read_lineage_chain,
    verify_lineage_snapshot_pin,
    verify_persisted_lineage_snapshot,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _pin(name: str, label: str) -> LineageSnapshotPin:
    return LineageSnapshotPin(name=name, sha256=_sha(label), size=1, device=1,
                              inode=hash(label) & ((1 << 63) - 1) or 1,
                              parent_device=1, parent_inode=1)


def _before(ordinal: int, journal: str, previous: tuple[str, str] | None = None) -> ProducerLineageBeforeIntent:
    return ProducerLineageBeforeIntent(
        run_id="run-1", journal_id=journal, ordinal=ordinal,
        predecessor_terminal_sha256=None if previous is None else previous[0],
        predecessor_lineage_sha256=None if previous is None else previous[1],
        archive=_pin("archive", f"after-a-{ordinal - 1}" if ordinal else "archive-0"),
        state=_pin("state", f"after-s-{ordinal - 1}" if ordinal else "state-0"),
    )


def _chain(tmp_path: Path, count: int = 2) -> tuple[list[str], list[ProducerLineageBeforeIntent]]:
    ids: list[str] = []
    befores: list[ProducerLineageBeforeIntent] = []
    previous: tuple[str, str] | None = None
    for ordinal in range(count):
        journal = f"batch-{ordinal}"
        (tmp_path / "evolution" / "producer-batches" / journal).mkdir(parents=True)
        before = _before(ordinal, journal, previous)
        staged = ProducerLineageStagedTransition(
            run_id="run-1", journal_id=journal, ordinal=ordinal,
            before_sha256=before.to_dict()["descriptor_sha256"], journal_sha256=_sha(f"journal-{ordinal}"),
            manifest_sha256=_sha(f"manifest-{ordinal}"), archive_after_sha256=_sha(f"after-a-{ordinal}"),
            state_after_sha256=_sha(f"after-s-{ordinal}"), candidate_ids=(f"candidate-{ordinal}",),
        )
        terminal = ProducerLineageTerminal(
            run_id="run-1", journal_id=journal, ordinal=ordinal,
            staged_sha256=staged.to_dict()["descriptor_sha256"], terminal_sha256=_sha(f"terminal-{ordinal}"),
            archive_after_sha256=staged.archive_after_sha256, state_after_sha256=staged.state_after_sha256,
        )
        for descriptor in (before, staged, terminal):
            persist_lineage_descriptor(tmp_path, descriptor)
        ids.append(journal); befores.append(before)
        previous = (terminal.terminal_sha256, terminal.to_dict()["descriptor_sha256"])
    return ids, befores


def test_lineage_descriptor_round_trip_and_digest() -> None:
    before = _before(0, "batch-0")
    wire = before.to_dict()
    assert parse_lineage_descriptor(wire) == before
    wire["ordinal"] = 1
    with pytest.raises(ProducerBundleLineageError, match="descriptor_digest_mismatch"):
        parse_lineage_descriptor(wire)


def test_lineage_chain_requires_adjacent_predecessor_and_order(tmp_path: Path) -> None:
    ids, _ = _chain(tmp_path)
    assert len(read_lineage_chain(tmp_path, ids, run_id="run-1")) == 2
    with pytest.raises(ProducerBundleLineageError, match="ordinal_invalid|predecessor_mismatch"):
        read_lineage_chain(tmp_path, ids[::-1], run_id="run-1")


def test_lineage_descriptor_is_create_only(tmp_path: Path) -> None:
    before = _before(0, "batch-0")
    (tmp_path / "evolution" / "producer-batches" / "batch-0").mkdir(parents=True)
    path, pin = persist_lineage_descriptor(tmp_path, before)
    assert persist_lineage_descriptor(tmp_path, before, expected_file_pin=pin) == (path, pin)
    with pytest.raises(ProducerBundleLineageError, match="original_file_pin_required"):
        persist_lineage_descriptor(tmp_path, before)


@pytest.mark.parametrize("payload", [
    {"kind": "unknown"},
    {"kind": "before", "descriptor_sha256": "0" * 64},
])
def test_lineage_parser_rejects_untrusted_shape(payload: dict[str, object]) -> None:
    with pytest.raises(ProducerBundleLineageError):
        parse_lineage_descriptor(payload)


def test_lineage_chain_is_bounded(tmp_path: Path) -> None:
    ids, _ = _chain(tmp_path)
    with pytest.raises(ProducerBundleLineageError, match="capacity_invalid"):
        read_lineage_chain(tmp_path, ids, run_id="run-1", max_batches=0)


def test_capture_snapshot_pin_is_read_only_and_exact(tmp_path: Path) -> None:
    path = tmp_path / "archive.jsonl"
    path.write_bytes(b'{"candidate_id":"one"}\n')
    path.chmod(0o600)
    pin = capture_lineage_snapshot_pin(path, name="archive")
    assert pin.size == path.stat().st_size
    assert pin.inode == path.stat().st_ino
    assert pin.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    verify_lineage_snapshot_pin(path, pin)
    path.write_bytes(b'{"candidate_id":"two"}\n')
    with pytest.raises(ProducerBundleLineageError, match="snapshot_pin_drift"):
        verify_lineage_snapshot_pin(path, pin)


@pytest.mark.parametrize("kind", ["pretty", "trailing", "duplicate"])
def test_descriptor_raw_bytes_require_exact_canonical_form(kind):
    descriptor = _before(0, "batch-0")
    encoded = descriptor.to_json()
    if kind == "pretty":
        encoded = json.dumps(descriptor.to_dict(), indent=2).encode()
    elif kind == "trailing":
        encoded += b"\n"
    else:
        encoded = encoded.replace(b'"ordinal":0', b'"ordinal":0,"ordinal":0')
    with pytest.raises(ProducerBundleLineageError, match="descriptor_noncanonical|json_invalid"):
        parse_lineage_descriptor(encoded)


@pytest.mark.parametrize("identifier", ["../other", "nested/batch", ".", "..", "\\nested", ""])
def test_derived_lineage_path_refuses_path_bearing_batch(tmp_path, identifier):
    with pytest.raises(ProducerBundleLineageError, match="journal_id_invalid"):
        lineage_directory(tmp_path, identifier)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("change", ["touch", "replace", "hardlink", "symlink", "mode"])
def test_retained_snapshot_refuses_metadata_and_identity_drift(tmp_path, change):
    source = tmp_path / "source"
    source.write_bytes(b"immutable snapshot")
    source.chmod(0o600)
    source_pin = capture_lineage_snapshot_pin(source, name="archive-before")
    (tmp_path / "evolution/producer-batches/batch-0").mkdir(parents=True)
    path, pin = persist_lineage_snapshot(tmp_path, "batch-0", name="archive-before", source=source,
                                         expected_pin=source_pin)
    assert pin.inode != source_pin.inode
    verify_persisted_lineage_snapshot(path, pin)
    if change == "touch":
        os.utime(path, ns=(pin.mtime_ns + 1, pin.mtime_ns + 1))
    elif change == "replace":
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes()); replacement.chmod(0o600)
        replacement.replace(path)
    elif change == "hardlink":
        os.link(path, path.with_name("hardlink"))
    elif change == "symlink":
        path.unlink(); path.symlink_to(source)
    else:
        path.chmod(0o400)
    with pytest.raises(ProducerBundleLineageError):
        verify_persisted_lineage_snapshot(path, pin)


def test_snapshot_replay_requires_original_destination_pin(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"pinned"); source.chmod(0o600)
    source_pin = capture_lineage_snapshot_pin(source, name="archive-before")
    (tmp_path / "evolution/producer-batches/batch-0").mkdir(parents=True)
    path, pin = persist_lineage_snapshot(tmp_path, "batch-0", name="archive-before", source=source,
                                         expected_pin=source_pin)
    assert persist_lineage_snapshot(tmp_path, "batch-0", name="archive-before", source=source,
                                     expected_pin=source_pin, expected_file_pin=pin) == (path, pin)
    with pytest.raises(ProducerBundleLineageError, match="original_file_pin_required"):
        persist_lineage_snapshot(tmp_path, "batch-0", name="archive-before", source=source,
                                  expected_pin=source_pin)


def test_creator_refuses_symlinked_parent_without_external_write(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (tmp_path / "evolution").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProducerBundleLineageError):
        persist_lineage_descriptor(tmp_path, _before(0, "batch-0"))
    assert list(outside.iterdir()) == []


def test_empty_archive_is_a_valid_explicit_snapshot(tmp_path):
    source = tmp_path / "empty"
    source.touch(mode=0o600)
    pin = capture_lineage_snapshot_pin(source, name="archive-before")
    assert pin.size == 0 and pin.sha256 == hashlib.sha256(b"").hexdigest()
    verify_lineage_snapshot_pin(source, pin)


@pytest.mark.parametrize("change", ["touch", "rewrite", "replace"])
def test_creation_readback_cannot_adopt_later_inode_or_stat(tmp_path, monkeypatch, change):
    (tmp_path / "evolution/producer-batches/batch-0").mkdir(parents=True)
    original = lineage._observe_file

    def drift_before_readback(path, **kwargs):
        raw = path.read_bytes()
        info = path.stat()
        if change == "touch":
            os.utime(path, ns=(info.st_mtime_ns + 1, info.st_mtime_ns + 1))
        elif change == "rewrite":
            path.write_bytes(raw)
        else:
            replacement = path.with_name("replacement")
            replacement.write_bytes(raw); replacement.chmod(0o600)
            replacement.replace(path)
        return original(path, **kwargs)

    monkeypatch.setattr(lineage, "_observe_file", drift_before_readback)
    with pytest.raises(ProducerBundleLineageError, match="snapshot_identity_drift"):
        persist_lineage_descriptor(tmp_path, _before(0, "batch-0"))
    assert (tmp_path / "evolution/producer-batches/batch-0/lineage/before.json").exists()


@pytest.mark.parametrize("retained", [True, -1, "0", MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES])
def test_snapshot_budget_refuses_before_source_read_or_destination_creation(tmp_path, monkeypatch, retained):
    def forbidden(*_args, **_kwargs):
        pytest.fail("budget refusal must precede filesystem observations")

    monkeypatch.setattr(lineage, "_observe_file", forbidden)
    with pytest.raises(ProducerBundleLineageError, match="snapshot_aggregate_invalid"):
        persist_lineage_snapshot(
            tmp_path, "batch-0", name="archive", source=tmp_path / "absent",
            expected_pin=_pin("archive", "one"), retained_bytes=retained,
        )
    with pytest.raises(ProducerBundleLineageError, match="snapshot_aggregate_invalid"):
        persist_lineage_bytes_snapshot(
            tmp_path, "batch-0", name="archive", raw=b"a", expected_sha256=_sha("a"),
            retained_bytes=retained,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field,value", [("size", "1"), ("inode", True), ("parent_inode", 0), ("mode", True)])
def test_malformed_held_pin_refuses_before_source_read(tmp_path, monkeypatch, field, value):
    pin = _pin("archive", "one")
    object.__setattr__(pin, field, value)

    def forbidden(*_args, **_kwargs):
        pytest.fail("malformed pin must precede filesystem observations")

    monkeypatch.setattr(lineage, "_observe_file", forbidden)
    with pytest.raises(ProducerBundleLineageError, match=f"snapshot_{field}_invalid"):
        persist_lineage_snapshot(
            tmp_path, "batch-0", name="archive", source=tmp_path / "absent", expected_pin=pin,
        )
    assert list(tmp_path.iterdir()) == []


def test_public_path_boundary_refuses_callbacks_and_traversal_without_effects(tmp_path):
    class CallbackPath:
        def __fspath__(self):
            pytest.fail("lineage paths must not invoke caller callbacks")

    for path in (CallbackPath(), tmp_path / ".." / "outside"):
        with pytest.raises(ProducerBundleLineageError, match="path_invalid"):
            capture_lineage_snapshot_pin(path, name="archive")
        with pytest.raises(ProducerBundleLineageError, match="path_invalid"):
            lineage_directory(path, "batch-0")
    assert list(tmp_path.iterdir()) == []
