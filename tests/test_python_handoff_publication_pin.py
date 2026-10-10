"""Original handoff file identity remains authority across publication boundaries."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _archive_projection,
    _batch_directory,
    _formal_execution_receipt,
    _initialize_native_population,
    _shinka_drafts,
)

from lunar_evolution import producer_bundle_recovery as recovery
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_rejection import (
    finalize_producer_bundle_all_rejected,
    inspect_producer_bundle_all_rejected,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)


def _setup(tmp_path: Path, *, candidate_value: int = 9) -> SimpleNamespace:
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (candidate_value,))
    journal_id = "python-retained-pin"
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
        sidecar_raw_sha256=digest, sidecar_pin_sha256=digest, launch_intent_sha256=digest,
        attestation_sha256=digest, runtime_manifest_sha256=digest, runtime_tree_sha256=digest,
        executable_owner_sha256=digest, native_execution_receipt_sha256=receipt["receipt_sha256"],
        terminal_sha256=digest, runtime_observation_sha256=digest,
        broker_transcript_sha256=digest, envelope_sha256=digest, materials_sha256=digest,
        contract_sha256=plan.contract_sha256, evaluator_sha256=plan.evaluator_fingerprint,
        runner_sha256=plan.runner_fingerprint, dependency_sha256=plan.dependency_sha256,
        environment_sha256=plan.environment_sha256, admission_plan_sha256=plan.digest(),
        request_budget=10, wall_timeout_seconds=60.0, deadline_unix=4102444800.0,
    )
    sidecar = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)
    return SimpleNamespace(
        context=context, strategy=strategy, drafts=drafts, plan=plan, batch=batch,
        handoff=handoff, pin=sidecar.file_pin, receipt=receipt, journal_id=journal_id,
        path=batch / "python-producer-admission-handoff.json",
    )


def _run(value: SimpleNamespace, **kwargs):
    return transaction.run_native_producer_bundle_publication_transaction(
        value.context.workspace, value.strategy, value.drafts, value.plan,
        journal_id=value.journal_id,
        native_execution_receipt_sha256=value.receipt["receipt_sha256"],
        python_handoff_sha256=value.handoff.handoff_sha256,
        python_handoff_file_pin=value.pin, **kwargs,
    )


def _replace_same_bytes(path: Path) -> None:
    before = path.stat()
    replacement = path.with_name("handoff-replacement.json")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    assert replacement.stat().st_ino != before.st_ino
    os.replace(replacement, path)


def _snapshot(workspace: Path) -> dict[Path, bytes]:
    return {path.relative_to(workspace): path.read_bytes()
            for path in workspace.rglob("*") if path.is_file()}


def _capture_stage(value: SimpleNamespace, monkeypatch) -> dict[str, object]:
    captured = {}

    def capture(workspace, journal, preflight, artifacts, **kwargs):
        captured.update(workspace=workspace, journal=journal, preflight=preflight,
                        artifacts=artifacts, kwargs=kwargs)
        raise transaction.NativeProducerBundleTransactionError("fixture_stage_capture")

    with monkeypatch.context() as patch:
        patch.setattr(transaction, "stage_producer_bundle_publication", capture)
        with pytest.raises(transaction.NativeProducerBundleTransactionError,
                           match="^fixture_stage_capture$"):
            _run(value)
    return captured


def _stage(captured: dict[str, object], *, journal=None, checkpoint=None):
    options = dict(captured["kwargs"])
    if checkpoint is not None:
        options["checkpoint"] = checkpoint
    return staging.stage_producer_bundle_publication(
        captured["workspace"], journal or captured["journal"], captured["preflight"],
        captured["artifacts"], **options,
    )


def test_transaction_persists_original_pin_and_recovery_keeps_it(tmp_path: Path) -> None:
    value = _setup(tmp_path)
    result = _run(value)
    prepared = parse_producer_bundle_publication_journal(value.batch / "journal.prepared.json")
    assert prepared.python_handoff_file_pin == value.pin
    assert result.published_journal.python_handoff_file_pin == value.pin
    before = _snapshot(value.context.workspace)
    assert recovery.resume_producer_bundle_publication(
        value.context.workspace, value.plan, result.published_journal,
    ).status == "published"
    assert _snapshot(value.context.workspace) == before


def test_transaction_missing_original_pin_refuses_before_workspace_io(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("workspace I/O was reached")

    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", forbidden)
    before = _snapshot(value.context.workspace)
    with pytest.raises(transaction.NativeProducerBundleTransactionError, match="python_handoff_invalid"):
        transaction.run_native_producer_bundle_publication_transaction(
            value.context.workspace, value.strategy, value.drafts, value.plan,
            journal_id=value.journal_id,
            native_execution_receipt_sha256=value.receipt["receipt_sha256"],
            python_handoff_sha256=value.handoff.handoff_sha256,
        )
    assert _snapshot(value.context.workspace) == before


@pytest.mark.parametrize("stage,evaluator_calls", [
    ("producer_prepared_intent_locked", 0),
    ("producer_draft_evaluation", 0),
    ("producer_draft_adjudication", 1),
    ("producer_staging_locked", 1),
])
def test_same_bytes_replacement_in_guard_refuses_without_publication(
    tmp_path: Path, monkeypatch, stage: str, evaluator_calls: int,
) -> None:
    value = _setup(tmp_path)
    calls = []
    original = value.context.bundle_pipeline.evaluate_draft_non_publishing

    def evaluate(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(value.context.bundle_pipeline, "evaluate_draft_non_publishing", evaluate)
    replaced = False

    def guard(current: str) -> None:
        nonlocal replaced
        if current == stage and not replaced:
            replaced = True
            _replace_same_bytes(value.path)

    before = _archive_projection(value.context.workspace)
    with pytest.raises(transaction.NativeProducerBundleTransactionError, match="python_handoff_invalid"):
        _run(value, continuation_guard=guard)
    assert replaced and len(calls) == evaluator_calls
    assert _archive_projection(value.context.workspace) == before
    assert not (value.context.workspace / "evolution/producer-publication.json").exists()
    assert not (value.batch / "stage").exists()


def test_timeout_callback_same_bytes_replacement_refuses_before_evaluator(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)
    pipeline = value.context.bundle_pipeline
    armed = False
    original_timeout = pipeline._effective_timeout

    def guard() -> None:
        if armed:
            _replace_same_bytes(value.path)

    def effective_timeout(stage: str) -> float:
        nonlocal armed
        armed = stage == "candidate_execution"
        try:
            return original_timeout(stage)
        finally:
            armed = False

    pipeline.set_continuation_guard(guard)
    monkeypatch.setattr(pipeline, "_effective_timeout", effective_timeout)
    calls = []

    def evaluator(*args, **kwargs):
        calls.append(True)
        raise AssertionError("evaluator must not run")

    from lunar_evolution import bundle_evolution

    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", evaluator)
    before = _archive_projection(value.context.workspace)
    with pytest.raises(transaction.NativeProducerBundleTransactionError, match="python_handoff_invalid"):
        _run(value)
    assert calls == []
    assert _archive_projection(value.context.workspace) == before
    assert not (value.batch / "stage").exists()


@pytest.mark.parametrize("mutation", ["same-bytes", "missing-anchor", "pin-retrofit", "missing-pin", "both-links-removed"])
def test_direct_stage_requires_original_pin_and_prepared_anchor(
    tmp_path: Path, monkeypatch, mutation: str,
) -> None:
    value = _setup(tmp_path)
    captured = _capture_stage(value, monkeypatch)
    journal = captured["journal"]
    if mutation == "same-bytes":
        _replace_same_bytes(value.path)
    elif mutation == "missing-anchor":
        (value.batch / "journal.prepared.json").unlink()
    elif mutation == "pin-retrofit":
        value.path.rename(value.batch / "original-handoff.json")
        new_sidecar = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff)
        journal = replace(journal, python_handoff_file_pin=new_sidecar.file_pin, journal_sha256=None)
    elif mutation == "missing-pin":
        journal = replace(journal, python_handoff_file_pin=None, journal_sha256=None)
    else:
        journal = replace(journal, python_handoff_sha256=None,
                          python_handoff_file_pin=None, journal_sha256=None)
    before = _snapshot(value.context.workspace)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="python_handoff_invalid"):
        _stage(captured, journal=journal)
    assert _snapshot(value.context.workspace) == before
    assert not (value.batch / "stage").exists()


def test_direct_stage_rechecks_pin_after_callback_before_stage_creation(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)
    captured = _capture_stage(value, monkeypatch)

    def checkpoint(stage: str) -> None:
        if stage == "producer_staging_locked":
            _replace_same_bytes(value.path)

    before = _archive_projection(value.context.workspace)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="python_handoff_invalid"):
        _stage(captured, checkpoint=checkpoint)
    assert _archive_projection(value.context.workspace) == before
    assert not (value.batch / "stage").exists()


def test_commit_replacement_before_unknown_keeps_staged_marker(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)
    captured = _capture_stage(value, monkeypatch)
    _stage(captured)
    journal = parse_producer_bundle_publication_journal(value.batch / "journal.json")
    marker = value.context.workspace / "evolution/producer-publication.json"
    marker_bytes = marker.read_bytes()
    before = _snapshot(value.context.workspace)

    def checkpoint(stage: str) -> None:
        if stage == "producer_commit_verified":
            _replace_same_bytes(value.path)

    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="python_handoff_invalid"):
        staging.commit_producer_bundle_publication(value.context.workspace, journal, checkpoint=checkpoint)
    assert marker.read_bytes() == marker_bytes
    assert json.loads(marker_bytes)["status"] == "staged"
    assert _snapshot(value.context.workspace) == before


def test_commit_replacement_after_unknown_preserves_unknown_without_terminal(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)
    captured = _capture_stage(value, monkeypatch)
    _stage(captured)
    journal = parse_producer_bundle_publication_journal(value.batch / "journal.json")
    original = staging._replace_file
    replaced = False

    def move(source, target):
        nonlocal replaced
        result = original(source, target)
        if not replaced:
            replaced = True
            _replace_same_bytes(value.path)
        return result

    monkeypatch.setattr(staging, "_replace_file", move)
    with pytest.raises(staging.ProducerBundlePublicationStagingError, match="python_handoff_invalid"):
        staging.commit_producer_bundle_publication(value.context.workspace, journal)
    marker = value.context.workspace / "evolution/producer-publication.json"
    assert replaced and json.loads(marker.read_bytes())["status"] == "unknown"
    assert not (value.batch / "terminal.json").exists()
    assert not (value.batch / "journal.published.json").exists()


@pytest.mark.parametrize("terminal", ["published", "all_rejected"])
@pytest.mark.parametrize("mutation", [
    "same-bytes", "missing-anchor", "missing-pin", "both-links-removed", "pin-retrofit",
])
def test_terminal_recovery_refuses_original_proof_drift_without_mutation_or_evaluation(
    tmp_path: Path, monkeypatch, terminal: str, mutation: str,
) -> None:
    value = _setup(tmp_path, candidate_value=9 if terminal == "published" else 20)
    result = _run(value)
    journal = result.terminal_journal
    assert journal.state == terminal
    if mutation == "same-bytes":
        _replace_same_bytes(value.path)
    elif mutation == "missing-anchor":
        (value.batch / "journal.prepared.json").unlink()
    elif mutation == "missing-pin":
        journal = replace(journal, python_handoff_file_pin=None, journal_sha256=None)
    elif mutation == "both-links-removed":
        journal = replace(journal, python_handoff_sha256=None,
                          python_handoff_file_pin=None, journal_sha256=None)
        destination = value.batch / ("journal.published.json" if terminal == "published" else "journal.json")
        destination.write_text(json.dumps(journal.to_dict(), sort_keys=True), encoding="utf-8")
    else:
        value.path.rename(value.batch / "original-handoff.json")
        new_sidecar = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff)
        journal = replace(journal, python_handoff_file_pin=new_sidecar.file_pin, journal_sha256=None)
        destination = value.batch / ("journal.published.json" if terminal == "published" else "journal.json")
        destination.write_text(json.dumps(journal.to_dict(), sort_keys=True), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("evaluator replay is forbidden")

    monkeypatch.setattr(value.context.bundle_pipeline, "evaluate_draft_non_publishing", forbidden)
    before = _snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="python_handoff_invalid"):
        recovery.resume_producer_bundle_publication(value.context.workspace, value.plan, journal)
    assert _snapshot(value.context.workspace) == before


def test_recovery_rechecks_original_pin_after_terminal_inspection(tmp_path: Path, monkeypatch) -> None:
    value = _setup(tmp_path)
    journal = _run(value).published_journal
    original = recovery._terminal

    def terminal(*args, **kwargs):
        result = original(*args, **kwargs)
        _replace_same_bytes(value.path)
        return result

    monkeypatch.setattr(recovery, "_terminal", terminal)
    before = _archive_projection(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError, match="python_handoff_invalid"):
        recovery.resume_producer_bundle_publication(value.context.workspace, value.plan, journal)
    assert _archive_projection(value.context.workspace) == before


def test_direct_rejected_replay_refuses_same_bytes_replacement(tmp_path: Path) -> None:
    value = _setup(tmp_path, candidate_value=20)
    journal = _run(value).terminal_journal
    assert journal.state == "all_rejected"
    _replace_same_bytes(value.path)
    before = _snapshot(value.context.workspace)
    with pytest.raises(ValueError, match="python_handoff|evidence_invalid"):
        inspect_producer_bundle_all_rejected(value.context.workspace, journal)
    assert _snapshot(value.context.workspace) == before


def test_existing_rejected_finalize_rechecks_pin_after_last_callback(tmp_path: Path) -> None:
    value = _setup(tmp_path, candidate_value=20)
    result = _run(value)
    before = _snapshot(value.context.workspace)
    calls = 0

    def checkpoint(stage: str) -> None:
        nonlocal calls
        if stage == "all_rejected":
            calls += 1
            if calls == 2:
                _replace_same_bytes(value.path)

    with pytest.raises(ValueError, match="python_handoff|evidence_invalid"):
        finalize_producer_bundle_all_rejected(
            value.context.workspace, result.journal, result.preflight, result.evaluations,
            authority=value.strategy.integrity_authority, checkpoint=checkpoint,
        )
    assert calls == 2
    assert _snapshot(value.context.workspace) == before


@pytest.mark.parametrize("boundary", ["stage", "recovery", "rejection"])
def test_mutated_callback_pin_refuses_before_serialization_or_workspace_io(
    tmp_path: Path, monkeypatch, boundary: str,
) -> None:
    value = _setup(tmp_path, candidate_value=20 if boundary == "rejection" else 9)
    calls = []

    class CallbackPin:
        def to_dict(self):
            calls.append(True)
            raise AssertionError("untrusted pin serializer was invoked")

    def forbidden(*args, **kwargs):
        raise AssertionError("workspace I/O was reached")

    if boundary == "stage":
        captured = _capture_stage(value, monkeypatch)
        object.__setattr__(captured["journal"], "python_handoff_file_pin", CallbackPin())
        monkeypatch.setattr(staging, "_workspace", forbidden)
        with pytest.raises(ValueError, match="python_handoff_invalid"):
            _stage(captured)
    else:
        result = _run(value)
        journal = result.terminal_journal if boundary == "recovery" else result.journal
        object.__setattr__(journal, "python_handoff_file_pin", CallbackPin())
        if boundary == "recovery":
            monkeypatch.setattr(recovery, "_workspace", forbidden)
            with pytest.raises(ValueError, match="python_handoff_invalid"):
                recovery.resume_producer_bundle_publication(value.context.workspace, value.plan, journal)
        else:
            with pytest.raises(ValueError, match="python_handoff|evidence_invalid"):
                finalize_producer_bundle_all_rejected(
                    value.context.workspace, journal, result.preflight, result.evaluations,
                    authority=value.strategy.integrity_authority,
                )
    assert calls == []
