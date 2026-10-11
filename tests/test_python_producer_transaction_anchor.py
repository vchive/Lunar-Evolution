"""Crash/retry and callback boundaries for a retained Python admission attempt."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _archive_projection,
    _batch_directory,
    _formal_execution_receipt,
    _initialize_native_population,
    _shinka_drafts,
)

from lunar_evolution import bundle_evolution, producer_bundle_transaction
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)
from lunar_evolution.python_producer_admission_anchor import (
    PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME,
    read_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)


def _python_transaction(tmp_path: Path):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-python-anchor"
    _batch_directory(context.workspace, journal_id)
    batch = context.workspace / "evolution" / "producer-batches" / journal_id
    receipt = _formal_execution_receipt(journal_id=journal_id)
    (batch / "execution-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    digest = "a" * 64
    handoff = build_python_producer_admission_handoff(
        run_id=journal_id, journal_id=journal_id, parent_task_id="producer",
        task_id="native-bundle-publication", binding_sha256=digest,
        sidecar_raw_sha256=digest, sidecar_pin_sha256=digest,
        launch_intent_sha256=digest, attestation_sha256=digest,
        runtime_manifest_sha256=digest, runtime_tree_sha256=digest,
        executable_owner_sha256=digest,
        native_execution_receipt_sha256=receipt["receipt_sha256"],
        terminal_sha256=digest, runtime_observation_sha256=digest,
        broker_transcript_sha256=digest, envelope_sha256=digest, materials_sha256=digest,
        contract_sha256=plan.contract_sha256, evaluator_sha256=plan.evaluator_fingerprint,
        runner_sha256=plan.runner_fingerprint, dependency_sha256=plan.dependency_sha256,
        environment_sha256=plan.environment_sha256, admission_plan_sha256=plan.digest(),
        request_budget=10, wall_timeout_seconds=60.375, deadline_unix=4102444800.125,
    )
    sidecar = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)

    def run(**options):
        return run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
            native_execution_receipt_sha256=receipt["receipt_sha256"],
            python_handoff_sha256=handoff.handoff_sha256,
            python_handoff_file_pin=sidecar.file_pin, **options,
        )

    return context, strategy, batch, handoff, run


def _cancel_before_evaluation(stage: str) -> None:
    if stage == "producer_draft_evaluation":
        raise SolveExecutionCancelled(stage)


def test_transaction_registers_first_anchor_without_rounding_original_limits(tmp_path: Path):
    context, _strategy, batch, handoff, run = _python_transaction(tmp_path)
    before = _archive_projection(context.workspace)
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=_cancel_before_evaluation)
    anchor_path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    anchor = read_python_producer_admission_attempt_anchor(anchor_path)
    assert (batch / "journal.prepared.json").is_file()
    assert anchor_path.stat().st_mode & 0o777 == 0o600
    assert anchor.handoff_sha256 == handoff.handoff_sha256
    assert anchor.binding_sha256 == handoff.binding_sha256
    assert anchor.request_budget == handoff.request_budget
    assert anchor.wall_timeout_seconds == handoff.wall_timeout_seconds == 60.375
    assert anchor.deadline_unix == handoff.deadline_unix == 4102444800.125
    assert _archive_projection(context.workspace) == before


def test_transaction_retry_reuses_retained_anchor_bytes_and_identity(tmp_path: Path):
    _context, _strategy, batch, _handoff, run = _python_transaction(tmp_path)
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=_cancel_before_evaluation)
    path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    retained = path.read_bytes(), path.stat()
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=_cancel_before_evaluation)
    assert path.read_bytes() == retained[0]
    assert path.stat() == retained[1]


@pytest.mark.parametrize("window", ["before-intent-write", "after-intent-write"])
def test_transaction_replays_original_anchor_across_prepared_intent_crash_windows(
    tmp_path: Path, monkeypatch, window: str,
):
    context, _strategy, batch, _handoff, run = _python_transaction(tmp_path)
    before = _archive_projection(context.workspace)
    path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    prepared_path = batch / "journal.prepared.json"

    def guard(stage):
        if stage == "producer_prepared_intent_locked":
            raise SolveExecutionCancelled(stage)

    original_persist = producer_bundle_transaction.persist_producer_bundle_prepared_intent

    def interrupted_persist(*args, **kwargs):
        original_persist(*args, **kwargs)
        raise SolveExecutionCancelled("producer_prepared_intent")

    if window == "after-intent-write":
        monkeypatch.setattr(
            producer_bundle_transaction, "persist_producer_bundle_prepared_intent", interrupted_persist,
        )
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=guard if window == "before-intent-write" else None)
    retained = path.read_bytes(), path.stat()
    assert prepared_path.exists() is (window == "after-intent-write")
    assert _archive_projection(context.workspace) == before
    monkeypatch.setattr(
        producer_bundle_transaction, "persist_producer_bundle_prepared_intent", original_persist,
    )
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=_cancel_before_evaluation)
    assert prepared_path.is_file()
    assert (path.read_bytes(), path.stat()) == retained
    assert _archive_projection(context.workspace) == before


@pytest.mark.parametrize("mode", ["missing", "changed", "symlink"])
def test_transaction_retry_refuses_lost_or_drifted_first_anchor_without_recreating_it(
    tmp_path: Path, monkeypatch, mode: str,
):
    context, _strategy, batch, _handoff, run = _python_transaction(tmp_path)
    with pytest.raises(SolveExecutionCancelled):
        run(continuation_guard=_cancel_before_evaluation)
    path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    original = read_python_producer_admission_attempt_anchor(path)
    if mode == "missing":
        path.unlink()
    elif mode == "changed":
        changed = replace(original, request_budget=original.request_budget + 1, anchor_sha256=None)
        path.write_bytes(changed.to_json())
    else:
        retained = batch / "moved-anchor.json"
        path.rename(retained)
        path.symlink_to(retained)
    before = _archive_projection(context.workspace)
    prepared = (batch / "journal.prepared.json").read_bytes()
    called = []
    monkeypatch.setattr(
        bundle_evolution, "evaluate_candidate_execution", lambda *args, **kwargs: called.append(True),
    )
    with pytest.raises(NativeProducerBundleTransactionError, match="python_producer_admission_anchor"):
        run()
    assert called == []
    assert _archive_projection(context.workspace) == before
    assert (batch / "journal.prepared.json").read_bytes() == prepared
    if mode == "missing":
        assert not path.exists()
    elif mode == "symlink":
        assert path.is_symlink()


@pytest.mark.parametrize("stage", ["producer_draft_evaluation", "producer_draft_adjudication", "producer_staging"])
def test_transaction_revalidates_anchor_after_each_caller_callback(tmp_path: Path, stage: str):
    context, _strategy, batch, _handoff, run = _python_transaction(tmp_path)
    path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    removed = False

    def guard(current: str) -> None:
        nonlocal removed
        if current == stage and not removed:
            removed = True
            path.unlink()

    before = _archive_projection(context.workspace)
    with pytest.raises(NativeProducerBundleTransactionError, match="python_producer_admission_anchor_missing"):
        run(continuation_guard=guard)
    assert removed
    assert not path.exists()
    assert _archive_projection(context.workspace) == before
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()


def test_transaction_revalidates_anchor_after_pipeline_timeout_guard(tmp_path: Path, monkeypatch):
    context, _strategy, batch, _handoff, run = _python_transaction(tmp_path)
    path = batch / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME
    pipeline = context.bundle_pipeline
    armed = False
    removed = False

    def guard():
        nonlocal removed
        if armed and not removed:
            path.unlink()
            removed = True

    pipeline.set_continuation_guard(guard)
    original_timeout = pipeline._effective_timeout

    def effective_timeout(stage: str) -> float:
        nonlocal armed
        armed = stage == "candidate_execution"
        try:
            return original_timeout(stage)
        finally:
            armed = False

    monkeypatch.setattr(pipeline, "_effective_timeout", effective_timeout)
    called = []
    monkeypatch.setattr(
        bundle_evolution, "evaluate_candidate_execution", lambda *args, **kwargs: called.append(True),
    )
    before = _archive_projection(context.workspace)
    with pytest.raises(NativeProducerBundleTransactionError, match="python_producer_admission_anchor_missing"):
        run()
    assert removed
    assert called == []
    assert _archive_projection(context.workspace) == before


def test_native_transaction_does_not_require_or_create_python_anchor(tmp_path: Path):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-native-no-python-anchor"
    _batch_directory(context.workspace, journal_id)
    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )
    assert result.publication_status == "published"
    assert not (context.workspace / "evolution" / "producer-batches" / journal_id / PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME).exists()
