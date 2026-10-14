"""Pure and local create-only contracts for opt-in multi-episode lineage evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.producer_bundle_lineage import (
    LineageSnapshotPin,
    ProducerBundleLineageError,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    parse_lineage_descriptor,
    persist_lineage_descriptor,
    read_lineage_chain,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _pin(name: str, label: str) -> LineageSnapshotPin:
    return LineageSnapshotPin(name=name, sha256=_sha(label), size=1, device=1, inode=hash(label) & ((1 << 63) - 1) or 1)


def _before(ordinal: int, journal: str, previous: tuple[str, str] | None = None) -> ProducerLineageBeforeIntent:
    return ProducerLineageBeforeIntent(
        run_id="run-1", journal_id=journal, ordinal=ordinal,
        predecessor_terminal_sha256=None if previous is None else previous[0],
        predecessor_lineage_sha256=None if previous is None else previous[1],
        archive=_pin("archive", f"archive-{ordinal}"), state=_pin("state", f"state-{ordinal}"),
    )


def _chain(tmp_path: Path, count: int = 2) -> tuple[list[str], list[ProducerLineageBeforeIntent]]:
    ids: list[str] = []
    befores: list[ProducerLineageBeforeIntent] = []
    previous: tuple[str, str] | None = None
    for ordinal in range(count):
        journal = f"batch-{ordinal}"
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
    path = persist_lineage_descriptor(tmp_path, before)
    assert persist_lineage_descriptor(tmp_path, before) == path
    changed = _before(0, "batch-0")
    object.__setattr__(changed, "archive", _pin("archive", "changed"))
    with pytest.raises(ProducerBundleLineageError, match="descriptor_conflict"):
        persist_lineage_descriptor(tmp_path, changed)


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
