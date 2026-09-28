"""Non-publishing native evaluation of journal-bound multi-file drafts."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.bundle_evolution import derive_native_draft_run_id, validate_bundle_draft
from lunar_evolution.evolution import CandidateArchive, EvolutionError, PopulationStrategy
from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_preflight import derive_producer_bundle_candidate_id
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationCandidate


def _files(root: Path) -> dict[str, tuple[bytes | None, int, int]]:
    result = {}
    for path in root.rglob("*"):
        if path.is_file() or path.is_dir():
            stat = path.lstat()
            result[path.relative_to(root).as_posix()] = (
                path.read_bytes() if path.is_file() else None, stat.st_dev, stat.st_ino,
            )
    return result


def _admission_plan(context, draft, *, bundle_id: str = "bundle-0"):
    bundle = validate_bundle_draft(draft, context.contract.digest())
    item = ProducerBundleAdmissionItem(
        bundle_id=bundle_id,
        bundle_sha256=bundle.digest(),
        draft_bundle_sha256=bundle.digest(),
        entrypoint=draft.filename,
        material_paths=tuple(sorted(draft.source_files or {draft.filename})),
        producer_fingerprint="d" * 64,
    )
    return ProducerBundleAdmissionPlan(
        contract_sha256=context.contract.digest(), evaluator_kind="bundle-fixture",
        evaluator_fingerprint="a" * 64, runner_fingerprint="b" * 64,
        dependency_sha256="c" * 64, environment_sha256="e" * 64, bundles=(item,),
    )


def _journal_candidate(context, draft, *, bundle_id: str = "bundle-0", parent_id=None):
    bundle = validate_bundle_draft(draft, context.contract.digest())
    candidate_id = derive_producer_bundle_candidate_id(
        "journal-strict", 0, bundle_id, bundle.digest(),
    )
    return ProducerBundlePublicationCandidate(
        candidate_id=candidate_id, bundle_id=bundle_id, bundle_sha256=bundle.digest(),
        parent_id=parent_id, generation=0, iteration=0, island_id=0,
        preparation_receipt_sha256="f" * 64,
    )


def test_draft_evaluation_is_deterministic_and_does_not_publish(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    bundle_sha = validate_bundle_draft(draft, context.contract.digest()).digest()
    candidate_id = "candidate-draft-1"
    expected_run = derive_native_draft_run_id("journal-draft-1", candidate_id, bundle_sha)
    before = _files(context.workspace)
    monkeypatch.setattr(strategy.archive, "next_id", lambda: pytest.fail("sequential ID allocated"))
    monkeypatch.setattr(strategy.archive, "persist", lambda *args, **kwargs: pytest.fail("archive published"))

    result = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-draft-1", candidate_id=candidate_id,
        iteration=0, generation=0, island_id=0,
    )
    assert result.run_id == expected_run
    assert result.run_root.name == ".bundle-run-" + expected_run
    assert result.report.combined_score == 7
    assert result.report.validity == 1
    assert re.fullmatch(r"\.bundle-run-[0-9a-f]{24}", result.run_root.name)
    assert (result.run_root / "attempt" / "completed.json").is_file()
    assert result.evaluation.evaluation_path.is_dir()
    assert _files(context.workspace) != before
    assert not (context.workspace / "evolution" / "candidates" / candidate_id).exists()
    assert not (context.workspace / "evolution" / "archive.jsonl").exists()
    assert not (context.workspace / "evolution" / "state.json").exists()


def test_draft_evaluation_preserves_populated_archive_and_candidate_inodes(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    assert PopulationStrategy(context).run().status == "completed"
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    before = _files(context.workspace)
    archive = CandidateArchive(context.workspace)
    monkeypatch.setattr(archive, "next_id", lambda: pytest.fail("sequential ID allocated"))
    monkeypatch.setattr(archive, "persist", lambda *args, **kwargs: pytest.fail("archive published"))

    result = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-draft-populated", candidate_id="candidate-draft-1",
        iteration=0, generation=0, island_id=0,
    )
    after = _files(context.workspace)
    for path, identity in before.items():
        assert after[path] == identity
    assert result.report.validity == 1
    assert result.report.combined_score == 7


def test_draft_evaluation_reuses_exact_retained_evidence(tmp_path, monkeypatch):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    calls = {"run": 0, "evaluate": 0}
    from lunar_evolution import bundle_evolution

    original_run = bundle_evolution.run_candidate_execution_recorded
    original_evaluate = bundle_evolution.evaluate_candidate_execution

    def run(*args, **kwargs):
        calls["run"] += 1
        return original_run(*args, **kwargs)

    def evaluate(*args, **kwargs):
        calls["evaluate"] += 1
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", run)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", evaluate)
    first = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-replay", candidate_id="candidate-1",
        iteration=0, generation=0, island_id=0,
    )
    second = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-replay", candidate_id="candidate-1",
        iteration=0, generation=0, island_id=0,
    )
    assert second.run_id == first.run_id
    assert second.execution.completion_sha256 == first.execution.completion_sha256
    assert second.evaluation.digest() == first.evaluation.digest()
    assert calls == {"run": 1, "evaluate": 1}


def test_journal_slot_requires_feature_152_plan_and_exact_lineage(tmp_path):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    candidate = _journal_candidate(context, draft)
    plan = _admission_plan(context, draft)

    with pytest.raises(EvolutionError, match="bundle_candidate_journal_admission_plan_invalid"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-strict", ordinal=0,
            journal_candidate=candidate,
        )

    mismatched = _admission_plan(context, draft, bundle_id="other-bundle")
    with pytest.raises(EvolutionError, match="bundle_candidate_journal_candidate_bundle_mapping_invalid"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-strict", ordinal=0,
            journal_candidate=candidate, admission_plan=mismatched,
        )

    class Parent:
        candidate_id = "foreign-parent"

    with pytest.raises(EvolutionError, match="bundle_candidate_lineage_invalid"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-strict", ordinal=0,
            journal_candidate=candidate, admission_plan=plan, parent=Parent(),
        )


@pytest.mark.parametrize("component", ["producer-batches", "journal", "native-drafts"])
def test_draft_evaluation_rejects_symlinked_batch_ancestors(tmp_path, component):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    evolution = context.workspace / "evolution"
    evolution.mkdir(parents=True, exist_ok=True)
    batches = evolution / "producer-batches"
    if component == "producer-batches":
        batches.symlink_to(tmp_path / "outside", target_is_directory=True)
    else:
        batches.mkdir()
        journal = batches / "journal-links"
        if component == "journal":
            journal.symlink_to(tmp_path / "outside", target_is_directory=True)
        else:
            journal.mkdir()
            (journal / "native-drafts").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(EvolutionError, match="bundle_candidate_destination_changed"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-links", candidate_id="candidate-1",
            iteration=0, generation=0, island_id=0,
        )


def test_draft_evaluation_rejects_replaced_candidate_directory(tmp_path):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    batch = context.workspace / "evolution" / "producer-batches" / "journal-replaced" / "native-drafts"
    batch.mkdir(parents=True)
    (batch / "candidate-1").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(EvolutionError, match="bundle_candidate_draft_exists"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-replaced", candidate_id="candidate-1",
            iteration=0, generation=0, island_id=0,
        )


def test_draft_binding_tamper_and_inode_drift_require_recovery(tmp_path):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    first = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-binding", candidate_id="candidate-1",
        iteration=0, generation=0, island_id=0,
    )
    binding_path = context.workspace / "evolution" / "producer-batches" / "journal-binding" / "native-drafts" / "candidate-1" / "draft-binding.json"
    binding = json.loads(binding_path.read_text())
    binding["candidate_id"] = "candidate-other"
    binding_path.write_text(json.dumps(binding, sort_keys=True, separators=(",", ":")))
    with pytest.raises(EvolutionError, match="bundle_candidate_draft_binding_mismatch"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-binding", candidate_id="candidate-1",
            iteration=0, generation=0, island_id=0,
        )

    # Restore the sidecar and replace the source directory with a byte-equivalent inode.
    binding["candidate_id"] = "candidate-1"
    binding_path.write_text(json.dumps(binding, sort_keys=True, separators=(",", ":")))
    source = first.source_root
    moved = source.with_name("source-original")
    source.rename(moved)
    shutil.copytree(moved, source)
    with pytest.raises(EvolutionError, match="bundle_candidate_draft_binding_mismatch"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-binding", candidate_id="candidate-1",
            iteration=0, generation=0, island_id=0,
        )


def test_draft_evaluation_rejects_extra_evaluation_directory_on_retry(tmp_path):
    context = build_context(tmp_path)
    strategy = PopulationStrategy(context)
    draft = draft_for_score(7)
    first = context.bundle_pipeline.evaluate_draft_non_publishing(
        strategy, draft, journal_id="journal-eval-extra", candidate_id="candidate-1",
        iteration=0, generation=0, island_id=0,
    )
    (first.run_root / "evaluations" / "extra").mkdir()
    with pytest.raises(EvolutionError, match="bundle_candidate_evidence_invalid|bundle_candidate_draft_exists"):
        context.bundle_pipeline.evaluate_draft_non_publishing(
            strategy, draft, journal_id="journal-eval-extra", candidate_id="candidate-1",
            iteration=0, generation=0, island_id=0,
        )
