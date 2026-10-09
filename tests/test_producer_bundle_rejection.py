from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _archive_projection,
    _batch_directory,
    _initialize_native_population,
    _shinka_drafts,
)

from lunar_evolution import (
    ProducerBundleRejectionError,
    finalize_producer_bundle_all_rejected,
    inspect_producer_bundle_all_rejected,
    producer_bundle_rejection,
    producer_bundle_transaction,
)
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
)
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_receipts import (
    ProducerBundleEvaluationReceipt,
    ProducerBundleExecutionReceipt,
)
from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)


def _inputs(tmp_path: Path):
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (999,))
    journal_id = "transaction-all-rejected-terminal"
    _batch_directory(context.workspace, journal_id)
    before = _archive_projection(context.workspace)
    return context, strategy, drafts, plan, journal_id, before


def _rejected(tmp_path: Path):
    context, strategy, drafts, plan, journal_id, before = _inputs(tmp_path)
    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )
    # This direct API check also verifies idempotence once the transaction calls finalization.
    terminal = finalize_producer_bundle_all_rejected(
        context.workspace, result.journal, result.preflight, result.evaluations,
        authority=strategy.integrity_authority,
    )
    batch = context.workspace / "evolution" / "producer-batches" / journal_id
    return context, strategy, drafts, plan, result, terminal, batch, before


def test_durable_all_rejected_inspection_retains_local_receipts_without_publication(tmp_path: Path) -> None:
    context, _strategy, _drafts, plan, result, terminal, batch, before = _rejected(tmp_path)
    assert terminal.state == "all_rejected"
    assert terminal.publication_phase == "committed"
    assert terminal.archive_after_sha256 == terminal.base_archive_sha256
    assert terminal.state_after_sha256 == terminal.base_state_sha256
    assert [item.status for item in terminal.candidates] == ["rejected"]
    assert all(item.execution_receipt_sha256 and item.evaluation_receipt_sha256 for item in terminal.candidates)
    assert inspect_producer_bundle_all_rejected(context.workspace, result.journal) == terminal
    assert inspect_producer_bundle_all_rejected(context.workspace, terminal) == terminal
    assert _archive_projection(context.workspace) == before
    assert not (batch / "stage").exists()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()
    assert not (context.workspace / "evolution" / "candidates" / terminal.candidates[0].candidate_id).exists()
    recovery = resume_producer_bundle_publication(context.workspace, plan, result.journal)
    assert recovery.status == "all_rejected"
    assert recovery.candidate_ids == ()
    assert recovery.rejected_candidate_ids == result.rejected_candidate_ids


@pytest.mark.parametrize("field", [
    "evaluation_digest", "evaluation_binding", "evaluation_report", "execution_cleanup",
    "execution_launch", "execution_result",
])
def test_rehashed_portable_receipts_cannot_replace_native_rejection_evidence(tmp_path: Path, field: str) -> None:
    context, _strategy, _drafts, _plan, result, terminal, batch, _before = _rejected(tmp_path)
    path = batch / "rejections" / (terminal.candidates[0].candidate_id + ".json")
    value = json.loads(path.read_bytes())
    if field.startswith("evaluation"):
        receipt = ProducerBundleEvaluationReceipt.from_dict(value["evaluation_receipt"])
        change = {
            "evaluation_digest": {"evaluation_sha256": "a" * 64},
            "evaluation_binding": {"binding": {**receipt.binding, "completion_sha256": "a" * 64}},
            "evaluation_report": {"report": {**receipt.report, "quality": 99}},
        }[field]
        changed = replace(receipt, **change, receipt_sha256=None)
        value["evaluation_receipt"] = changed.to_dict()
    else:
        receipt = ProducerBundleExecutionReceipt.from_dict(value["execution_receipt"])
        changed = replace(receipt, **{
            {"execution_cleanup": "cleanup_sha256", "execution_launch": "launch_intent_sha256",
             "execution_result": "result_sha256"}[field]: "a" * 64,
        }, receipt_sha256=None)
        value["execution_receipt"] = changed.to_dict()
    # The retained native evidence stays exact. A fully self-consistent portable receipt still
    # must equal the receipt reconstructed from that retained local evidence.
    with pytest.raises(ProducerBundleRejectionError, match="producer_bundle_rejection_receipt_mismatch"):
        producer_bundle_rejection._verify_receipts(
            context.workspace, result.journal, result.journal.candidates[0], value,
        )


def test_rejection_requires_python_handoff_to_match_journal_even_after_rehash(tmp_path: Path) -> None:
    context, _strategy, _drafts, _plan, result, terminal, batch, _before = _rejected(tmp_path)
    path = batch / "rejections" / (terminal.candidates[0].candidate_id + ".json")
    value = json.loads(path.read_bytes())
    evaluation = ProducerBundleEvaluationReceipt.from_dict(value["evaluation_receipt"])
    changed = replace(evaluation, python_handoff_sha256="f" * 64, receipt_sha256=None)
    value["evaluation_receipt"] = changed.to_dict()
    with pytest.raises(ProducerBundleRejectionError, match="producer_bundle_rejection_adjudication_invalid"):
        producer_bundle_rejection._verify_receipts(
            context.workspace, result.journal, result.journal.candidates[0], value,
        )


@pytest.mark.parametrize("when", [1, 2])
@pytest.mark.parametrize("kind", ["cancelled", "expired"])
def test_terminal_checkpoint_stops_before_locked_work_or_terminal_commit(
    tmp_path: Path, monkeypatch, when: int, kind: str,
) -> None:
    context, strategy, drafts, plan, journal_id, before = _inputs(tmp_path)
    original = producer_bundle_transaction.finalize_producer_bundle_all_rejected
    calls = []

    def checkpoint(stage: str):
        if stage != "all_rejected":
            return
        calls.append(stage)
        if len(calls) == when:
            if kind == "cancelled":
                raise SolveExecutionCancelled(stage)
            raise SolveExecutionBudgetExceeded(stage, started_at=1, deadline=2, observed_at=2)

    def finalizer(*args, **kwargs):
        kwargs["checkpoint"] = checkpoint
        return original(*args, **kwargs)

    monkeypatch.setattr(producer_bundle_transaction, "finalize_producer_bundle_all_rejected", finalizer)
    error = SolveExecutionCancelled if kind == "cancelled" else SolveExecutionBudgetExceeded
    with pytest.raises(error):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
        )
    batch = context.workspace / "evolution" / "producer-batches" / journal_id
    assert not (batch / "journal.json").exists()
    assert _archive_projection(context.workspace) == before
    prepared = producer_bundle_rejection.parse_producer_bundle_publication_journal(batch / "journal.prepared.json")
    if when == 1:
        assert inspect_producer_bundle_all_rejected(context.workspace, prepared) is None
    else:
        assert (batch / "rejections.json").exists()
        with pytest.raises(ProducerBundleRejectionError, match="producer_bundle_rejection_recovery_required"):
            inspect_producer_bundle_all_rejected(context.workspace, prepared)
    assert not (batch / "stage").exists()
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("mutation", ["source", "receipt", "receipt_inode", "intent_inode", "terminal", "prefix"])
def test_all_rejected_inspection_rejects_changed_terminal_evidence(tmp_path: Path, mutation: str) -> None:
    context, _strategy, _drafts, plan, result, terminal, batch, before = _rejected(tmp_path)
    receipt_path = batch / "rejections" / (terminal.candidates[0].candidate_id + ".json")
    if mutation == "source":
        source = result.evaluations[0].source_root / result.evaluations[0].bundle.entrypoint
        source.write_bytes(source.read_bytes() + b"\n# changed\n")
    elif mutation == "receipt":
        value = json.loads(receipt_path.read_bytes())
        value["evaluation_receipt"]["report"]["validity"] = 1
        receipt_path.write_text(json.dumps(value), encoding="utf-8")
    elif mutation in {"receipt_inode", "intent_inode"}:
        original = receipt_path if mutation == "receipt_inode" else batch / "journal.prepared.json"
        replacement = original.with_suffix(".replacement")
        replacement.write_bytes(original.read_bytes())
        os.replace(replacement, original)
    elif mutation == "terminal":
        value = json.loads((batch / "journal.json").read_bytes())
        value["terminal_marker_sha256"] = "a" * 64
        (batch / "journal.json").write_text(json.dumps(value), encoding="utf-8")
    else:
        state_path = context.workspace / "evolution" / "state.json"
        state_path.write_bytes(state_path.read_bytes() + b"\n")
    with pytest.raises(ProducerBundleRejectionError):
        inspect_producer_bundle_all_rejected(context.workspace, result.journal)
    with pytest.raises((ProducerBundleRecoveryError, ValueError)):
        resume_producer_bundle_publication(context.workspace, plan, result.journal)
    if mutation != "prefix":
        assert _archive_projection(context.workspace) == before


def test_partial_all_rejected_terminal_never_adopts_another_attempt(tmp_path: Path) -> None:
    context, _strategy, _drafts, _plan, result, _terminal, batch, before = _rejected(tmp_path)
    (batch / "journal.json").unlink()
    with pytest.raises(ProducerBundleRejectionError, match="producer_bundle_rejection_recovery_required"):
        inspect_producer_bundle_all_rejected(context.workspace, result.journal)
    assert _archive_projection(context.workspace) == before


def test_all_rejected_transaction_retry_only_inspects_durable_terminal(tmp_path: Path, monkeypatch) -> None:
    context, strategy, drafts, plan, result, terminal, _batch, before = _rejected(tmp_path)

    def fail_evaluation(*args, **kwargs):
        raise AssertionError("a terminal retry must not call draft execution or evaluation")

    monkeypatch.setattr(strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", fail_evaluation)
    retried = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=result.journal.journal_id,
    )
    assert retried.publication_status == "all_rejected"
    assert retried.terminal_journal == terminal
    assert retried.evaluations == ()
    assert retried.admitted_candidate_ids == ()
    assert retried.rejected_candidate_ids == result.rejected_candidate_ids
    assert _archive_projection(context.workspace) == before


def test_all_rejected_terminal_changed_task_is_rejected_without_reexecution(tmp_path: Path, monkeypatch) -> None:
    context, strategy, drafts, plan, result, _terminal, _batch, before = _rejected(tmp_path)

    def fail_evaluation(*args, **kwargs):
        raise AssertionError("a changed terminal retry must not execute")

    monkeypatch.setattr(strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", fail_evaluation)
    with pytest.raises(NativeProducerBundleTransactionError):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=result.journal.journal_id,
            task_id="another-task",
        )
    assert _archive_projection(context.workspace) == before
