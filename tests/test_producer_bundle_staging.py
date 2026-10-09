from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_bundle_native_intent import native_publication as _native_publication_fixture

import lunar_evolution.producer_bundle_staging as staging
from lunar_evolution.producer_bundle_preflight import (
    ProducerBundlePreflightReceipt,
    _authority_digest,
)
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
    parse_producer_bundle_publication_journal,
)
from lunar_evolution.producer_bundle_staging import (
    ProducerBundlePublicationArtifact,
    ProducerBundlePublicationStagingError,
    commit_producer_bundle_publication,
    stage_producer_bundle_publication,
)


def d(letter: str) -> str:
    return letter * 64


def fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    batch = workspace / "evolution" / "producer-batches" / "journal-1"
    batch.mkdir(parents=True)
    (workspace / "evolution" / "candidates").mkdir()
    (workspace / "evolution" / "archive.jsonl").write_bytes(b"")
    state = {"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": []}}
    state_bytes = json.dumps(state, sort_keys=True).encode()
    (workspace / "evolution" / "state.json").write_bytes(state_bytes)
    candidate = ProducerBundlePublicationCandidate(
        "candidate-1", "bundle-1", d("a"), None, 0, 0, 0, d("b"),
    )
    journal = build_producer_bundle_publication_journal(
        journal_id="journal-1", run_id="run-1", parent_task_id="parent-1", task_id="task-1",
        admission_sha256=d("c"), archive_prefix_sha256=d("d"),
        base_archive_sha256=hashlib.sha256(b"").hexdigest(),
        base_state_sha256=hashlib.sha256(state_bytes).hexdigest(), contract_sha256=d("0"),
        evaluator_kind="callback", evaluator_fingerprint=d("1"), runner_fingerprint=d("2"),
        dependency_sha256=d("3"), environment_sha256=d("4"), budget_sha256=d("5"),
        strategy="population", population_config_sha256=d("6"), num_islands=1,
        candidates=(candidate,),
    )
    receipt = ProducerBundlePreflightReceipt(
        journal_id="journal-1", run_id="run-1", task_id="task-1", plan_sha256=journal.admission_sha256,
        archive_prefix_sha256=d("d"), base_archive_sha256=journal.base_archive_sha256,
        base_state_sha256=journal.base_state_sha256, authority_sha256=_authority_digest(journal),
        candidate_ids=(candidate.candidate_id,), record_count=0,
        workspace_relative="evolution/producer-batches/journal-1",
    )
    artifact = ProducerBundlePublicationArtifact(
        candidate.candidate_id, {"main.py": "print('ok')\n"},
        {"candidate_id": candidate.candidate_id}, {"receipt_sha256": d("9")},
        execution_receipt_sha256=d("c"), evaluation_receipt_sha256=d("e"),
    )
    return workspace, journal, receipt, artifact


def test_stage_is_zero_exposure_and_commit_publishes_atomically(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    manifest = stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,),
        state_after={"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": ["candidate-1"]}},
    )
    assert manifest.status == "staged"
    assert not (workspace / "evolution" / "archive.jsonl").read_bytes()
    assert not (workspace / "evolution" / "candidates" / "candidate-1").exists()
    assert (workspace / "evolution" / "producer-publication.json").is_file()
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    final = commit_producer_bundle_publication(workspace, staged)
    assert final.state == "published"
    assert (workspace / "evolution" / "candidates" / "candidate-1" / "main.py").read_text() == "print('ok')\n"
    assert json.loads((workspace / "evolution" / "archive.jsonl").read_text()) == {
        "candidate_id": "candidate-1",
    }
    assert not (workspace / "evolution" / "producer-publication.json").exists()
    assert parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    ).state == "published"


@pytest.fixture
def native_publication(tmp_path: Path, monkeypatch):
    """Reuse the native transaction capture without executing a publication commit."""
    return _native_publication_fixture.__wrapped__(tmp_path, monkeypatch)


def test_stage_rejects_python_handoff_receipt_when_journal_omits_it(native_publication) -> None:
    value = native_publication
    artifact = value["artifacts"][0]
    from lunar_evolution.producer_bundle_receipts import ProducerBundleEvaluationReceipt

    evaluation = ProducerBundleEvaluationReceipt.from_dict(dict(artifact.evaluation_receipt))
    linked = replace(evaluation, python_handoff_sha256=d("f"), receipt_sha256=None)
    changed = replace(
        artifact,
        evaluation_receipt=linked.to_dict(), evaluation_receipt_sha256=linked.digest(),
    )
    with pytest.raises(ProducerBundlePublicationStagingError,
                       match="^producer_bundle_publication_evidence_invalid$"):
        stage_producer_bundle_publication(
            value["workspace"], value["journal"], value["preflight"], (changed,),
            **value["kwargs"],
        )
    assert not (value["workspace"] / "evolution/producer-publication.json").exists()


def test_native_artifact_rejects_python_handoff_mismatch_even_with_rehashed_receipt(
    native_publication,
) -> None:
    value = native_publication
    artifact = value["artifacts"][0]
    from lunar_evolution.producer_bundle_receipts import ProducerBundleEvaluationReceipt
    evaluation = ProducerBundleEvaluationReceipt.from_dict(dict(artifact.evaluation_receipt))
    linked = replace(
        value["journal"], native_execution_receipt_sha256=d("e"),
        python_handoff_sha256=d("f"), journal_sha256=None,
    )
    changed = replace(evaluation, python_handoff_sha256=d("0"), receipt_sha256=None)
    changed_artifact = replace(
        artifact,
        evaluation_receipt=changed.to_dict(), evaluation_receipt_sha256=changed.digest(),
    )
    with pytest.raises(ProducerBundlePublicationStagingError,
                       match="^producer_bundle_publication_evidence_invalid$"):
        staging._validate_native_artifact(
            changed_artifact, linked.candidates[0], linked,
        )


def test_stage_rejects_missing_receipt_sequence_without_marker(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    incomplete = ProducerBundlePublicationArtifact(
        artifact.candidate_id, artifact.source_files, artifact.record, artifact.receipt,
    )
    with pytest.raises(ProducerBundlePublicationStagingError) as caught:
        stage_producer_bundle_publication(
            workspace, journal, receipt, (incomplete,), state_after={"strategy": "population"},
        )
    assert caught.value.code == "producer_bundle_publication_receipt_sequence_invalid"
    assert not (workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("field,value", [
    ("journal_id", "journal-other"), ("run_id", "run-other"), ("task_id", "task-other"),
    ("plan_sha256", d("f")), ("archive_prefix_sha256", d("f")),
    ("base_archive_sha256", d("f")), ("base_state_sha256", d("f")),
    ("authority_sha256", d("f")), ("candidate_ids", ("candidate-other",)),
])
def test_stage_rejects_foreign_preflight_without_writes(
    tmp_path: Path, field: str, value: object,
) -> None:
    workspace, journal, preflight, artifact = fixture(tmp_path)
    changes = {field: value, "receipt_sha256": None}
    if field == "journal_id":
        changes["workspace_relative"] = "evolution/producer-batches/" + str(value)
    changed = replace(preflight, **changes)
    before = {path.relative_to(workspace): path.read_bytes()
              for path in workspace.rglob("*") if path.is_file()}
    with pytest.raises(ProducerBundlePublicationStagingError, match="^producer_bundle_publication_preflight_mismatch$"):
        stage_producer_bundle_publication(
            workspace, journal, changed, (artifact,), state_after={"strategy": "population"},
        )
    after = {path.relative_to(workspace): path.read_bytes()
             for path in workspace.rglob("*") if path.is_file()}
    assert before == after
    assert not (workspace / "evolution/producer-batches/journal-1/stage").exists()


def test_stage_revalidates_preflight_receipt_digest(tmp_path: Path) -> None:
    workspace, journal, preflight, artifact = fixture(tmp_path)
    object.__setattr__(preflight, "receipt_sha256", d("f"))
    with pytest.raises(ProducerBundlePublicationStagingError, match="^producer_bundle_publication_preflight_invalid$"):
        stage_producer_bundle_publication(
            workspace, journal, preflight, (artifact,), state_after={"strategy": "population"},
        )
    assert not (workspace / "evolution/producer-publication.lock").exists()


def test_stage_rejects_wrong_preflight_record_count(tmp_path: Path) -> None:
    workspace, journal, preflight, artifact = fixture(tmp_path)
    changed = replace(preflight, record_count=1, receipt_sha256=None)
    with pytest.raises(ProducerBundlePublicationStagingError, match="^producer_bundle_publication_preflight_mismatch$"):
        stage_producer_bundle_publication(
            workspace, journal, changed, (artifact,), state_after={"strategy": "population"},
        )
    assert not (workspace / "evolution/producer-batches/journal-1/stage").exists()
    assert not (workspace / "evolution/producer-publication.json").exists()


def test_commit_with_tampered_stage_is_unknown_and_marker_remains(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), state_after={"strategy": "population"},
    )
    archive = workspace / "evolution" / "producer-batches" / "journal-1" / "stage" / "archive.jsonl"
    archive.write_bytes(archive.read_bytes() + b"tampered")
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    with pytest.raises(ProducerBundlePublicationStagingError):
        commit_producer_bundle_publication(workspace, staged)
    assert (workspace / "evolution" / "producer-publication.json").is_file()


def test_mixed_batch_records_rejected_without_publishing_it(tmp_path: Path) -> None:
    workspace, journal, receipt, artifact = fixture(tmp_path)
    rejected = ProducerBundlePublicationCandidate(
        "candidate-2", "bundle-2", d("2"), None, 0, 0, 0, d("3"),
    )
    journal = build_producer_bundle_publication_journal(
        **{**journal.to_dict(), "journal_sha256": None,
           "num_islands": 1, "candidates": (journal.candidates[0], rejected)},
    )
    receipt = replace(receipt, candidate_ids=("candidate-1", "candidate-2"), receipt_sha256=None)
    stage_producer_bundle_publication(
        workspace, journal, receipt, (artifact,), rejected_candidate_ids=("candidate-2",),
        state_after={"strategy": "population"},
    )
    staged = parse_producer_bundle_publication_journal(
        workspace / "evolution" / "producer-batches" / "journal-1" / "journal.json"
    )
    assert [item.status for item in staged.candidates] == ["admitted", "rejected"]


def test_all_rejected_batch_is_not_staged(tmp_path: Path) -> None:
    workspace, journal, receipt, _ = fixture(tmp_path)
    with pytest.raises(ProducerBundlePublicationStagingError) as caught:
        stage_producer_bundle_publication(
            workspace, journal, receipt, (), rejected_candidate_ids=("candidate-1",),
            state_after={"strategy": "population"},
        )
    assert caught.value.code == "producer_bundle_publication_no_admitted_candidates"
    assert not (workspace / "evolution" / "producer-publication.json").exists()
