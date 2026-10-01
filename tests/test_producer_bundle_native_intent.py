"""Publication cannot reuse native draft evidence under a different prepared request."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _batch_directory,
    _initialize_native_population,
    _shinka_drafts,
)

import lunar_evolution.producer_bundle_staging as staging
import lunar_evolution.producer_bundle_transaction as transaction
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_preflight import _authority_digest
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_receipts import _retained_entry, _retained_evidence_digest
from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)


@pytest.fixture
def native_publication(tmp_path: Path, monkeypatch):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    _batch_directory(context.workspace, "intent-publication")
    captured = {}

    def capture(workspace, journal, preflight, artifacts, **kwargs):
        captured.update(workspace=workspace, journal=journal, preflight=preflight,
                        artifacts=artifacts, kwargs=kwargs, plan=plan)
        raise transaction.NativeProducerBundleTransactionError("fixture_stage_capture")

    with monkeypatch.context() as patch:
        patch.setattr(transaction, "stage_producer_bundle_publication", capture)
        with pytest.raises(transaction.NativeProducerBundleTransactionError,
                           match="^fixture_stage_capture$"):
            transaction.run_native_producer_bundle_publication_transaction(
                context.workspace, strategy, drafts, plan, journal_id="intent-publication",
            )
    return captured


def _stage(value, *, journal=None, artifacts=None):
    journal = journal or value["journal"]
    # A different, internally valid preflight is still not authority to reuse old execution.
    preflight = replace(value["preflight"], authority_sha256=_authority_digest(journal),
                        receipt_sha256=None)
    return staging.stage_producer_bundle_publication(
        value["workspace"], journal, preflight,
        value["artifacts"] if artifacts is None else artifacts, **value["kwargs"],
    )


def _staged_journal(value):
    return parse_producer_bundle_publication_journal(
        value["workspace"] / "evolution/producer-batches/intent-publication/journal.json",
    )


def _assert_not_exposed(value):
    workspace = value["workspace"]
    assert not (workspace / "evolution/producer-publication.json").exists()
    assert not (workspace / "evolution/producer-batches/intent-publication/stage").exists()
    assert not (workspace / "evolution/candidates" / value["artifacts"][0].candidate_id).exists()


@pytest.mark.parametrize("field,changed", [
    ("parent_task_id", "another-parent"),
    ("budget_sha256", "f" * 64),
])
def test_stage_rejects_native_artifact_from_another_prepared_request(
    native_publication, field, changed,
):
    value = native_publication
    journal = replace(value["journal"], **{field: changed}, journal_sha256=None)
    with pytest.raises(staging.ProducerBundlePublicationStagingError,
                       match="^producer_bundle_publication_prepared_intent_mismatch$"):
        _stage(value, journal=journal)
    _assert_not_exposed(value)


@pytest.mark.parametrize("removed", ["descriptor", "binding", "intent"])
def test_stage_cannot_downgrade_native_transaction_by_dropping_retained_evidence(
    native_publication, removed,
):
    value = native_publication
    artifact = value["artifacts"][0]
    evidence = artifact.retained_evidence
    if removed == "descriptor":
        evidence = None
    else:
        suffix = "/draft-binding.json" if removed == "binding" else "/journal.prepared.json"
        evidence = {**evidence, "entries": [
            entry for entry in evidence["entries"] if not entry["path"].endswith(suffix)
        ]}
        evidence["evidence_sha256"] = _retained_evidence_digest(evidence)
    with pytest.raises(staging.ProducerBundlePublicationStagingError,
                       match="^producer_bundle_publication_prepared_intent_mismatch$"):
        _stage(value, artifacts=(replace(artifact, retained_evidence=evidence),))
    _assert_not_exposed(value)


def test_native_prepared_request_is_revalidated_after_adjudication_and_publication(native_publication):
    value = native_publication
    _stage(value)
    journal = _staged_journal(value)
    assert resume_producer_bundle_publication(value["workspace"], value["plan"], journal).status == "resume"
    published = staging.commit_producer_bundle_publication(value["workspace"], journal)
    assert resume_producer_bundle_publication(value["workspace"], value["plan"], published).status == "published"


@pytest.mark.parametrize("digest", [None, "e" * 64])
def test_native_binding_requires_exact_prepared_journal_digest(native_publication, digest):
    value = native_publication
    artifact = value["artifacts"][0]
    evidence = artifact.retained_evidence
    entry = next(item for item in evidence["entries"] if item["path"].endswith("/draft-binding.json"))
    binding_path = value["workspace"] / entry["path"]
    binding = json.loads(binding_path.read_text())
    if digest is None:
        binding.pop("journal_sha256")
    else:
        binding["journal_sha256"] = digest
    binding_path.write_text(json.dumps(binding, sort_keys=True))
    # Refresh the file descriptor deliberately: a valid byte/inode envelope alone must not
    # replace the semantic comparison with this publication's prepared request.
    evidence = {**evidence, "entries": [
        _retained_entry(binding_path, value["workspace"]) if item is entry else item
        for item in evidence["entries"]
    ]}
    evidence["evidence_sha256"] = _retained_evidence_digest(evidence)
    with pytest.raises(staging.ProducerBundlePublicationStagingError,
                       match="^producer_bundle_publication_prepared_intent_mismatch$"):
        _stage(value, artifacts=(replace(artifact, retained_evidence=evidence),))
    _assert_not_exposed(value)


@pytest.mark.parametrize("boundary", ["commit", "recovery"])
def test_durable_cross_journal_stage_is_rejected_before_commit_or_recovery(
    native_publication, monkeypatch, boundary,
):
    value = native_publication
    changed = replace(value["journal"], parent_task_id="another-parent", journal_sha256=None)
    # Construct the internally valid stage an older publisher could write, keeping the
    # original retained execution, binding and prepared-intent bytes entirely unchanged.
    with monkeypatch.context() as patch:
        patch.setattr(staging, "verify_native_publication_intent", lambda *args, **kwargs: args[3])
        _stage(value, journal=changed)
    staged = _staged_journal(value)
    if boundary == "commit":
        with pytest.raises(staging.ProducerBundlePublicationStagingError,
                           match="^producer_bundle_publication_prepared_intent_mismatch$"):
            staging.commit_producer_bundle_publication(value["workspace"], staged)
    else:
        with pytest.raises(ProducerBundleRecoveryError,
                           match="^producer_bundle_recovery_evidence_changed$"):
            resume_producer_bundle_publication(value["workspace"], value["plan"], staged)
    assert not (value["workspace"] / "evolution/candidates" / value["artifacts"][0].candidate_id).exists()
