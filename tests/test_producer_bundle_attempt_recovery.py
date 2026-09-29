"""Provider-free read-only unknown-attempt inspection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _batch_directory,
    _initialize_native_population,
    _shinka_drafts,
)

from lunar_evolution import (
    bundle_evolution,
    producer_bundle_attempt_recovery,
    producer_bundle_transaction,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.candidate_process_interruption import build_process_interruption_receipt
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_attempt_recovery import (
    NativeProducerAttemptRecoveryError,
    inspect_native_producer_bundle_unknown_attempt,
)
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)


def _retained(tmp_path: Path, monkeypatch):
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "interrupted-inspect"
    _batch_directory(context.workspace, journal_id)
    captured = []
    original_evaluate = context.bundle_pipeline.evaluate_draft_non_publishing

    def capture(*args, **kwargs):
        result = original_evaluate(*args, **kwargs)
        captured.append(result)
        return result

    def stop_before_stage(*args, **kwargs):
        raise RuntimeError("fixture stop")

    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing", capture)
    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", stop_before_stage)
    with pytest.raises(NativeProducerBundleTransactionError, match="recovery_required"):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
        )
    assert len(captured) == 1
    batch = context.workspace / "evolution" / "producer-batches" / journal_id
    journal = parse_producer_bundle_publication_journal(batch / "journal.prepared.json")
    result = captured[0]
    return context, drafts, plan, journal, result


def _receipt(path: Path, *, stage: str, request_sha256: str) -> None:
    receipt = build_process_interruption_receipt({
        "reason": "cancelled", "stage": stage, "pid": 2001, "pgid": 2001,
        "exit_code": -15, "cleanup": "verified", "ownership_release": "observed",
        "observed_ms": 15,
    }, request_sha256=request_sha256, stage=stage)
    path.write_bytes(canonical_json(receipt))


def _inspect(workspace, plan, journal, result):
    return inspect_native_producer_bundle_unknown_attempt(
        workspace, plan, journal, candidate_id=result.candidate_id,
    )


def _make_unknown(result, stage: str) -> Path:
    if stage == "candidate_execution":
        attempt = result.run_root / "attempt"
        (attempt / "completed.json").unlink()
        (attempt / "result.json").unlink()
        (attempt / "cleanup.json").unlink(missing_ok=True)
        receipt = attempt / "interrupted.json"
        request_sha256 = result.execution.launch_intent_sha256
    else:
        evaluation = result.evaluation.evaluation_path
        (evaluation / "evaluation.json").unlink()
        receipt = evaluation / "interrupted.json"
        request_sha256 = hashlib.sha256((evaluation / "request.json").read_bytes()).hexdigest()
    _receipt(receipt, stage=stage, request_sha256=request_sha256)
    return receipt


def test_completed_attempt_is_outside_unknown_inspection(tmp_path, monkeypatch):
    context, _drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    with pytest.raises(NativeProducerAttemptRecoveryError, match="known_terminal"):
        _inspect(context.workspace, plan, journal, result)


def test_candidate_stop_inspection_is_read_only_and_never_retryable(tmp_path, monkeypatch):
    context, drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    workspace = context.workspace
    attempt = result.run_root / "attempt"
    (attempt / "completed.json").unlink()
    (attempt / "result.json").unlink()
    if (attempt / "cleanup.json").exists():
        (attempt / "cleanup.json").unlink()
    _receipt(
        attempt / "interrupted.json", stage="candidate_execution",
        request_sha256=result.execution.launch_intent_sha256,
    )
    state_before = (workspace / "evolution" / "state.json").read_bytes()
    archive_before = (workspace / "evolution" / "archive.jsonl").read_bytes()
    receipt_before = (attempt / "interrupted.json").read_bytes()

    observed = _inspect(workspace, plan, journal, result)
    assert (observed.status, observed.stage, observed.reason, observed.cleanup) == (
        "unknown", "candidate_execution", "cancelled", "verified",
    )
    assert (attempt / "interrupted.json").read_bytes() == receipt_before
    assert (workspace / "evolution" / "state.json").read_bytes() == state_before
    assert (workspace / "evolution" / "archive.jsonl").read_bytes() == archive_before

    (attempt / "interrupted.json").unlink()
    missing = _inspect(workspace, plan, journal, result)
    assert (missing.stage, missing.reason, missing.cleanup) == (
        "candidate_execution", "missing_terminal_evidence", "unknown",
    )

    def replay_forbidden(*args, **kwargs):
        pytest.fail("an unknown attempt must not execute again")

    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", replay_forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", replay_forbidden)
    with pytest.raises(NativeProducerBundleTransactionError):
        run_native_producer_bundle_publication_transaction(
            workspace, PopulationStrategy(context), drafts, plan, journal_id=journal.journal_id,
        )


def test_evaluation_stop_and_missing_receipt_remain_unknown(tmp_path, monkeypatch):
    context, _drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    workspace = context.workspace
    evaluation = result.evaluation.evaluation_path
    (evaluation / "evaluation.json").unlink()
    request_sha256 = hashlib.sha256((evaluation / "request.json").read_bytes()).hexdigest()
    _receipt(evaluation / "interrupted.json", stage="evaluation", request_sha256=request_sha256)

    observed = _inspect(workspace, plan, journal, result)
    assert (observed.stage, observed.reason, observed.cleanup) == ("evaluation", "cancelled", "verified")

    (evaluation / "interrupted.json").unlink()
    observed = _inspect(workspace, plan, journal, result)
    assert (observed.stage, observed.reason, observed.cleanup) == (
        "evaluation", "missing_terminal_evidence", "unknown",
    )


def test_inspector_reopens_retained_unknown_from_new_interpreter(tmp_path, monkeypatch):
    context, _drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    _make_unknown(result, "evaluation")
    plan_path = tmp_path / "admission-plan.json"
    plan_path.write_bytes(canonical_json(plan.to_dict()))
    prepared = (
        context.workspace / "evolution" / "producer-batches" / journal.journal_id
        / "journal.prepared.json"
    )
    archive = context.workspace / "evolution" / "archive.jsonl"
    archive_before = archive.read_bytes()
    script = """
import json
import sys
from dataclasses import asdict
from lunar_evolution.producer_bundle_admission import parse_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_attempt_recovery import inspect_native_producer_bundle_unknown_attempt
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal

plan = parse_producer_bundle_admission_plan(sys.argv[2])
journal = parse_producer_bundle_publication_journal(sys.argv[3])
result = inspect_native_producer_bundle_unknown_attempt(
    sys.argv[1], plan, journal, candidate_id=sys.argv[4],
)
print(json.dumps(asdict(result)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(context.workspace), str(plan_path),
         str(prepared), result.candidate_id],
        check=True, capture_output=True, text=True,
    )
    observed = json.loads(completed.stdout)
    assert observed["status"] == "unknown"
    assert archive.read_bytes() == archive_before


@pytest.mark.parametrize("stage", ["candidate_execution", "evaluation"])
def test_unknown_inspection_rejects_same_byte_receipt_replacement_during_read(
    tmp_path, monkeypatch, stage,
):
    context, _drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    receipt = _make_unknown(result, stage)
    original = producer_bundle_attempt_recovery._interruption

    def replace_after_read(*args, **kwargs):
        observed = original(*args, **kwargs)
        replacement = receipt.with_name("interrupted-replacement.json")
        replacement.write_bytes(receipt.read_bytes())
        os.replace(replacement, receipt)
        return observed

    monkeypatch.setattr(producer_bundle_attempt_recovery, "_interruption", replace_after_read)
    with pytest.raises(NativeProducerAttemptRecoveryError, match="evidence_changed"):
        _inspect(context.workspace, plan, journal, result)


@pytest.mark.parametrize("tamper", [
    "source", "binding", "receipt", "receipt_binding", "prepared", "request", "inode", "coexist", "advanced",
])
def test_unknown_inspection_rejects_changed_evidence(tmp_path, monkeypatch, tamper):
    context, _drafts, plan, journal, result = _retained(tmp_path, monkeypatch)
    workspace = context.workspace
    evaluation = result.evaluation.evaluation_path
    (evaluation / "evaluation.json").unlink()
    request = evaluation / "request.json"
    _receipt(
        evaluation / "interrupted.json", stage="evaluation",
        request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
    )
    if tamper == "source":
        (result.source_root / result.bundle.files[0].path).write_text("changed")
    elif tamper == "binding":
        (result.source_root.parent / "draft-binding.json").write_text("{}")
    elif tamper == "receipt":
        path = evaluation / "interrupted.json"
        value = json.loads(path.read_bytes())
        value["cleanup"] = "unknown"
        path.write_bytes(canonical_json(value))
    elif tamper == "receipt_binding":
        path = evaluation / "interrupted.json"
        _receipt(path, stage="evaluation", request_sha256="0" * 64)
    elif tamper == "prepared":
        (workspace / "evolution" / "producer-batches" / journal.journal_id / "journal.prepared.json").write_text("{}")
    elif tamper == "request":
        value = json.loads(request.read_bytes())
        value["binding"]["completion_sha256"] = "0" * 64
        request.write_bytes(canonical_json(value))
    elif tamper == "inode":
        source = result.source_root
        replacement = source.with_name("source-new")
        shutil.copytree(source, replacement)
        moved = source.with_name("source-old")
        source.rename(moved)
        os.replace(replacement, source)
    elif tamper == "advanced":
        batch = workspace / "evolution" / "producer-batches" / journal.journal_id
        (batch / "journal.json").write_bytes((batch / "journal.prepared.json").read_bytes())
    else:
        (evaluation / "evaluation.json").write_text("{}")
    with pytest.raises(NativeProducerAttemptRecoveryError):
        _inspect(workspace, plan, journal, result)
