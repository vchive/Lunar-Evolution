"""An interrupted candidate move retains uncertainty without recovery repair."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from test_producer_bundle_recovery import _journal, _plan

from lunar_evolution import bundle_evolution, producer_bundle_transaction, producer_process
from lunar_evolution import producer_bundle_recovery as recovery
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution.producer_bundle_preflight import preflight_producer_bundle_publication
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal


def _snapshot(root: Path) -> dict[Path, tuple[object, ...]]:
    """Retain names, identities, metadata and bytes; reading may change atime."""
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        identity = (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
        content = (
            path.read_bytes() if stat.S_ISREG(info.st_mode)
            else os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
        )
        result[path.relative_to(root)] = (*identity, content)
    return result


def test_interrupted_first_candidate_move_retains_unknown_and_recovery_is_readonly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = {"producer": 0, "evaluator": 0, "retry": 0, "publication": 0}

    def forbidden(effect):
        def fail(*args, **kwargs):
            effects[effect] += 1
            pytest.fail(f"interrupted publication invoked {effect}")
        return fail

    monkeypatch.setattr(producer_process, "run_producer_process", forbidden("producer"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("producer"))
    monkeypatch.setattr(subprocess, "run", forbidden("producer"))
    monkeypatch.setattr(
        bundle_evolution, "evaluate_candidate_execution", forbidden("evaluator"),
    )
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline,
        "evaluate_draft_non_publishing", forbidden("evaluator"),
    )
    monkeypatch.setattr(
        producer_bundle_transaction, "run_native_producer_bundle_publication_transaction",
        forbidden("retry"),
    )

    plan = _plan()
    prepared = _journal(plan, state="prepared")
    workspace = tmp_path / "workspace"
    evolution = workspace / "evolution"
    batch = evolution / "producer-batches" / prepared.journal_id
    batch.mkdir(parents=True)
    (evolution / "candidates").mkdir()
    state = {
        "strategy": "population", "config": {"strategy": "population", "num_islands": 1},
        "active_ids": {"0": []},
    }
    (evolution / "state.json").write_bytes(json.dumps(state, sort_keys=True).encode())
    (evolution / "archive.jsonl").write_bytes(b"")
    candidate_id = prepared.candidates[0].candidate_id
    artifact = staging.ProducerBundlePublicationArtifact(
        candidate_id, {"main.py": b"# Inert retained bytes; never executed.\n"},
        {"candidate_id": candidate_id}, {"receipt_sha256": "9" * 64},
        execution_receipt_sha256="c" * 64, evaluation_receipt_sha256="e" * 64,
    )
    preflight = preflight_producer_bundle_publication(workspace, plan, prepared)
    manifest = staging.stage_producer_bundle_publication(
        workspace, prepared, preflight, (artifact,),
        state_after={**state, "active_ids": {"0": [candidate_id]}},
    )
    staged = parse_producer_bundle_publication_journal(batch / "journal.json")
    assert staged.state == "publishing"
    assert staged.budget_sha256 == prepared.budget_sha256
    before_commit = _snapshot(workspace)
    source = batch / "stage" / "candidates" / candidate_id
    target = evolution / "candidates" / candidate_id
    source_identity = source.stat().st_dev, source.stat().st_ino
    source_files = {path.relative_to(source): path.read_bytes() for path in source.iterdir()}
    assert not target.exists()
    marker_path = evolution / "producer-publication.json"
    assert json.loads(marker_path.read_bytes())["status"] == "staged"

    original_replace = staging.os.replace
    replacements = []
    completed_moves = []
    interruption = OSError("inert interruption after successful candidate replacement")

    def replace_then_interrupt(source_path, target_path, *args, **kwargs):
        replacements.append((Path(source_path), Path(target_path)))
        result = original_replace(source_path, target_path, *args, **kwargs)
        if Path(source_path) == source and Path(target_path) == target:
            # The real rename must succeed before the simulated interruption is raised.
            assert not source.exists()
            assert target.is_dir()
            completed_moves.append((Path(source_path), Path(target_path)))
            raise interruption
        return result

    monkeypatch.setattr(staging.os, "replace", replace_then_interrupt)
    with pytest.raises(staging.ProducerBundlePublicationStagingError) as caught:
        staging.commit_producer_bundle_publication(workspace, staged)
    assert caught.value.code == "producer_bundle_publication_commit_unknown"
    assert caught.value.__cause__ is interruption
    assert completed_moves == [(source, target)]
    assert (target.stat().st_dev, target.stat().st_ino) == source_identity
    assert {path.relative_to(target): path.read_bytes() for path in target.iterdir()} == source_files
    marker = json.loads(marker_path.read_bytes())
    assert marker["status"] == "unknown"
    assert marker["journal_sha256"] == staged.digest()
    assert marker["manifest_sha256"] == manifest.digest()
    after_commit = _snapshot(workspace)
    for relative in (
        "evolution/archive.jsonl", "evolution/state.json",
        f"evolution/producer-batches/{prepared.journal_id}/journal.json",
        f"evolution/producer-batches/{prepared.journal_id}/journal.staged.json",
        f"evolution/producer-batches/{prepared.journal_id}/preflight.json",
        f"evolution/producer-batches/{prepared.journal_id}/manifest.json",
        f"evolution/producer-batches/{prepared.journal_id}/stage/archive.jsonl",
        f"evolution/producer-batches/{prepared.journal_id}/stage/state.json",
    ):
        assert after_commit[Path(relative)] == before_commit[Path(relative)]
    assert not (batch / "terminal.json").exists()
    assert not (batch / "journal.published.json").exists()

    for module in (staging, producer_bundle_transaction):
        monkeypatch.setattr(module, "stage_producer_bundle_publication", forbidden("publication"))
        monkeypatch.setattr(module, "commit_producer_bundle_publication", forbidden("publication"))
    retained_replacements = tuple(replacements)
    # Both the original authority and its durable staged projection must refuse read-only.
    for caller_journal in (prepared, staged):
        with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
            recovery.resume_producer_bundle_publication(workspace, plan, caller_journal)
        assert caught.value.code == "producer_bundle_recovery_unknown_terminal"
        assert _snapshot(workspace) == after_commit
        assert tuple(replacements) == retained_replacements
        assert completed_moves == [(source, target)]
        assert effects == {"producer": 0, "evaluator": 0, "retry": 0, "publication": 0}
