"""A renamed lock cannot authorize further publication writes by its former owner."""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from test_producer_bundle_staging import fixture

from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution.producer_bundle_intent import persist_producer_bundle_prepared_intent
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal


def replace_lock(workspace):
    path = workspace / "evolution/producer-publication.lock"
    path.rename(path.with_suffix(".old"))
    path.write_bytes(b"")


@pytest.mark.parametrize("operation", ["new", "replace", "move", "directory"])
def test_old_lock_owner_cannot_write_or_move_after_replacement(tmp_path, operation):
    workspace, *_ = fixture(tmp_path)
    output = workspace / "evolution/result.json"
    output.write_bytes(b"original")
    source = workspace / "evolution/source.json"
    source.write_bytes(b"source")
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="lock_changed"), staging._locked(workspace):
        replace_lock(workspace)
        if operation == "new":
            staging._write_new(output.with_suffix(".new"), b"new", maximum=100)
        elif operation == "replace":
            staging._replace_existing(output, b"new", maximum=100)
        elif operation == "move":
            staging._replace_file(source, output)
        else:
            staging._ensure_directory(workspace / "evolution", "new-directory")
    assert output.read_bytes() == b"original"
    assert source.read_bytes() == b"source"
    assert not output.with_suffix(".new").exists()
    assert not (workspace / "evolution/new-directory").exists()


def test_prepared_intent_checks_owner_after_checkpoint_mutates_lock(tmp_path):
    workspace, journal, *_ = fixture(tmp_path)
    def checkpoint(stage):
        if stage == "producer_prepared_intent_locked":
            replace_lock(workspace)
    with pytest.raises(Exception, match="lock_changed|write_failed"):
        persist_producer_bundle_prepared_intent(workspace, journal, checkpoint=checkpoint)
    assert not (workspace / "evolution/producer-batches/journal-1/journal.prepared.json").exists()


def test_wrapped_lock_keeps_context_guard_without_yielding_callback(tmp_path, monkeypatch):
    workspace, journal, receipt, artifact = fixture(tmp_path)
    original = staging._locked
    @contextmanager
    def wrapped(*args, **kwargs):
        with original(*args, **kwargs):
            yield
    monkeypatch.setattr(staging, "_locked", wrapped)
    def checkpoint(stage):
        if stage == "producer_staging_prepared":
            replace_lock(workspace)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="lock_changed"):
        staging.stage_producer_bundle_publication(
            workspace, journal, receipt, (artifact,), state_after={"strategy": "population"},
            checkpoint=checkpoint,
        )
    assert not (workspace / "evolution/producer-publication.json").exists()
    assert not (workspace / "evolution/producer-batches/journal-1/journal.json").exists()
    assert (workspace / "evolution/producer-batches/journal-1/stage").exists()


def test_lock_replacement_after_unknown_marker_preserves_prefix_and_unknown(tmp_path, monkeypatch):
    workspace, journal, receipt, artifact = fixture(tmp_path)
    staging.stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), state_after={"strategy": "population"},
    )
    journal = parse_producer_bundle_publication_journal(
        workspace / "evolution/producer-batches/journal-1/journal.json",
    )
    original = staging._replace_existing
    def replace_and_change_lock(path, content, **kwargs):
        original(path, content, **kwargs)
        if path.name == "producer-publication.json" and json.loads(content)["status"] == "unknown":
            replace_lock(workspace)
    monkeypatch.setattr(staging, "_replace_existing", replace_and_change_lock)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="lock_changed"):
        staging.commit_producer_bundle_publication(workspace, journal)
    assert (workspace / "evolution/archive.jsonl").read_bytes() == b""
    assert not (workspace / "evolution/candidates/candidate-1").exists()
    assert json.loads((workspace / "evolution/producer-publication.json").read_bytes())["status"] == "unknown"


def test_replaced_owner_cannot_acquire_second_lock_in_same_context(tmp_path):
    workspace, *_ = fixture(tmp_path)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="lock_changed"), staging._locked(workspace):
        replace_lock(workspace)
        with staging._locked(workspace):
            pytest.fail("a stale owner acquired the replacement inode")
