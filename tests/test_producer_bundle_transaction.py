"""Provider-free end-to-end producer import, local re-evaluation and publication."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import build_context

from lunar_evolution import bundle_evolution, producer_bundle_transaction
from lunar_evolution.bundle_delivery import inspect_bundle_delivery, publish_bundle_delivery
from lunar_evolution.bundle_evolution import read_bundle_delivery_materials
from lunar_evolution.evolution import CandidateArchive, CandidateDraft, PopulationStrategy
from lunar_evolution.producer_bundle_admission import build_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_handoff import BundleGroup, prepare_producer_bundle_manifest
from lunar_evolution.producer_bundle_population import prepare_producer_bundle_drafts
from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionError,
    run_native_producer_bundle_publication_transaction,
)
from lunar_evolution.producer_process import (
    ProducerProcessError,
    _digest_without,
    parse_producer_execution_receipt,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff,
)
from lunar_evolution.shinka_handoff import export_shinka_result

PRODUCER_FINGERPRINT = "d" * 64


def _candidate_source(value: int) -> str:
    return f'''import json, os
from pathlib import Path

limit = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "value").read_text())
value = {value}
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({{"value": value}}))
'''


def _shinka_drafts(tmp_path: Path, context, values: tuple[int, ...]):
    results = tmp_path / "shinka-run"
    results.mkdir()
    database = sqlite3.connect(results / "programs.sqlite")
    database.execute(
        """
        CREATE TABLE programs (
            id TEXT, code TEXT, language TEXT, parent_id TEXT, generation INTEGER,
            combined_score REAL, correct BOOLEAN
        )
        """
    )
    for index, value in enumerate(values):
        source = _candidate_source(value)
        generation = results / f"gen_{index}"
        generation.mkdir()
        (generation / "main.py").write_text(source, encoding="utf-8")
        database.execute(
            "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"program-{index}", source, "python", f"program-{index - 1}" if index else None,
             index, float(100 - index), 1),
        )
    database.commit()
    database.close()

    export = tmp_path / "shinka-export"
    envelope = export_shinka_result(
        results,
        export,
        contract_sha256=context.contract.digest(),
        producer_fingerprint=PRODUCER_FINGERPRINT,
        producer_id="shinka",
        producer_run_id="fixture-run",
        program_ids=tuple(f"program-{index}" for index in range(len(values))),
    )
    groups = tuple(
        BundleGroup(f"bundle-{index}", item.path, (item.path,))
        for index, item in enumerate(envelope.materials)
    )
    bundles = prepare_producer_bundle_manifest(
        export, envelope, groups, context.contract, PRODUCER_FINGERPRINT, "shinka",
    )
    drafts = prepare_producer_bundle_drafts(export, bundles)
    strategy = PopulationStrategy(context)
    authority = strategy.integrity_authority
    plan = build_producer_bundle_admission_plan(
        drafts,
        contract_sha256=authority.contract_sha256,
        evaluator_kind=authority.evaluator_kind,
        evaluator_fingerprint=authority.evaluator_fingerprint,
        runner_fingerprint=authority.runner_fingerprint,
        dependency_sha256=authority.dependency_sha256,
        environment_sha256=authority.environment_sha256,
    )
    return strategy, drafts, plan, export


def _batch_directory(workspace: Path, journal_id: str) -> None:
    (workspace / "evolution" / "producer-batches" / journal_id).mkdir(parents=True)


def _formal_execution_receipt(
    *, journal_id: str, run_id: str | None = None, parent_task_id: str = "producer",
    task_id: str = "native-bundle-publication",
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "1",
        "protocol": "lunar-producer-process-execution-v1",
        "launch_id": "launch-formal",
        "journal_id": journal_id,
        "run_id": run_id or journal_id,
        "parent_task_id": parent_task_id,
        "task_id": task_id,
        "intent_sha256": "a" * 64,
        "attestation_sha256": "b" * 64,
        "consumption_sha256": "c" * 64,
        "registration_sha256": "d" * 64,
        "executable_identity": "e" * 64,
        "pid": 4242,
        "pgid": 4242,
        "owner_identity": {"pid": 4242, "start_time": 1},
        "status": "completed",
        "exit_code": 0,
        "gate_released": True,
        "request_timeout_seconds": 30,
        "max_requests": 10,
        "output_max_bytes": 4096,
        "wall_timeout_seconds": 60,
        "request_count": 0,
        "stdout_evidence": {
            "stream": "stdout", "bytes_observed": 0, "sha256": "f" * 64,
            "truncated": False, "capture_status": "complete",
        },
        "stderr_evidence": {
            "stream": "stderr", "bytes_observed": 0, "sha256": "0" * 64,
            "truncated": False, "capture_status": "complete",
        },
        "envelope_evidence": None,
        "cleanup_status": "cleaned",
        "cleanup_sha256": "1" * 64,
        "execution_binding": "linux-sealed-memfd",
        "execution_snapshot_relative_path": None,
        "execution_snapshot_sha256": "2" * 64,
        "execution_snapshot_size": 0,
        "failure_code": None,
        "previous_receipt_sha256": "d" * 64,
        "trusted_execution": {
            "terminal_sha256": "3" * 64,
            "stream_capture_sha256": "4" * 64,
            "output_capture_sha256": "5" * 64,
            "cleanup_sha256": "6" * 64,
            "broker_coverage": "brokered_requests_only",
            "broker_journal_relative_path": ".host-request-journal/requests",
            "broker_journal_identity": {
                "launch_id": "launch-formal",
                "journal_id": journal_id,
                "run_id": run_id or journal_id,
                "parent_task_id": parent_task_id,
                "task_id": task_id,
                "intent_sha256": "a" * 64,
                "request_timeout_seconds": 30,
                "max_requests": 10,
                "wall_deadline_ns": 1,
            },
            "broker_journal_file_identity": [1, 2],
            "broker_journal_sha256": "7" * 64,
            "broker_journal_bytes": 1,
            "broker_admitted_count": 0,
            "broker_declared_count_matches": True,
        },
    }
    receipt["receipt_sha256"] = _digest_without(receipt, "receipt_sha256")
    return receipt


def test_formal_receipt_parser_rejects_missing_broker_journal_file_identity() -> None:
    receipt = _formal_execution_receipt(journal_id="journal-formal")
    trusted = receipt["trusted_execution"]
    assert isinstance(trusted, dict)
    del trusted["broker_journal_file_identity"]
    receipt["receipt_sha256"] = _digest_without(receipt, "receipt_sha256")
    with pytest.raises(ProducerProcessError) as failure:
        parse_producer_execution_receipt(receipt)
    assert failure.value.code == "producer_process_receipt_trusted_execution_invalid"


def _initialize_native_population(strategy: PopulationStrategy, values: tuple[int, ...] = (1, 2)) -> None:
    active = {index: [] for index in range(strategy.config.num_islands)}
    for index, value in enumerate(values):
        island = index % strategy.config.num_islands
        candidate = strategy._persist(
            CandidateDraft.from_files({"main.py": _candidate_source(value)}, "main.py"),
            iteration=0,
            generation=0,
            parent=None,
            island_id=island,
        )
        if candidate.evaluation.validity == 1:
            active[island].append(candidate.candidate_id)
    strategy._trim(active)
    best = strategy.archive.best()
    strategy._state(
        "running",
        0,
        active_ids={str(key): value for key, value in active.items()},
        stagnation=0,
        error=None,
        best_candidate_id=best.candidate_id if best is not None else None,
        rng_seed=strategy.config.rng_seed,
        last_migration_iteration=0,
    )


def _archive_projection(workspace: Path) -> tuple[bytes, bytes, list[dict[str, object]]]:
    archive_path = workspace / "evolution" / "archive.jsonl"
    state_path = workspace / "evolution" / "state.json"
    raw_archive = archive_path.read_bytes()
    raw_state = state_path.read_bytes()
    archive = CandidateArchive(workspace, requested_strategy="population", read_only=True)
    records = archive.records()
    archive.validate_candidate_integrity(require_all=True, records=records)
    return raw_archive, raw_state, [item.to_dict() for item in records]


def test_shinka_sqlite_drafts_are_locally_reevaluated_and_published_with_readback(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    initial_archive = CandidateArchive(context.workspace, requested_strategy="population", read_only=True)
    initial_state = initial_archive.read_state()
    initial_count = len(initial_archive.records())
    assert sum(len(items) for items in initial_state["active_ids"].values()) == initial_state["config"]["population_size"]
    strategy, drafts, plan, export = _shinka_drafts(tmp_path, context, (9, 999))
    journal_id = "transaction-mixed"
    _batch_directory(context.workspace, journal_id)

    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )

    assert [item.report.validity for item in result.evaluations] == [1, 0]
    assert [item.report.combined_score for item in result.evaluations] == [9, 0]
    assert len(result.admitted_candidate_ids) == 1
    assert len(result.rejected_candidate_ids) == 1
    assert result.publication_status == "published"
    assert result.published_journal is not None
    assert result.published_journal.state == "published"
    assert "native_execution_receipt_sha256" not in result.journal.to_dict()
    assert (export / "producer-result.json").is_file()

    archive = CandidateArchive(context.workspace, requested_strategy="population", read_only=True)
    records = archive.records()
    archive.validate_candidate_integrity(require_all=True, records=records)
    committed = {item.candidate_id: item for item in records}
    assert len(records) == initial_count + 1
    admitted = committed[result.admitted_candidate_ids[0]]
    assert admitted.evaluation.validity == 1
    assert admitted.evaluation.combined_score == 9
    assert admitted.integrity is not None
    assert admitted.bundle_evidence is not None
    assert result.rejected_candidate_ids[0] not in committed
    state = archive.read_state()
    assert state["candidate_archive_sha256"]
    assert sum(len(items) for items in state["active_ids"].values()) == state["config"]["population_size"]
    admission_events = state["producer_admissions"]["events"]
    assert admission_events == [{
        "after_iteration": 0,
        "candidate_ids": list(result.admitted_candidate_ids),
    }]
    assert state["active_ids"]["0"] == [admitted.candidate_id]
    assert state["best_candidate_id"] == admitted.candidate_id
    materials = read_bundle_delivery_materials(context.workspace, admitted)
    delivery_root = tmp_path / "delivery"
    delivery_root.mkdir()
    delivered = publish_bundle_delivery(delivery_root, identity={
        "candidate_id": admitted.candidate_id,
        "contract_sha256": context.contract.digest(),
        "bundle_sha256": admitted.bundle_evidence["bundle_sha256"],
        "receipt_sha256": admitted.receipt_sha256,
        "evaluation_sha256": admitted.bundle_evidence["evaluation_sha256"],
    }, materials=materials)
    assert inspect_bundle_delivery(delivered.delivery_path) == delivered
    assert json.loads((delivered.delivery_path / "output/result.json").read_bytes()) == {"value": 9}
    journal_path = context.workspace / "evolution" / "producer-batches" / journal_id / "journal.json"
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "published"
    resumed = strategy.resume()
    assert resumed.status == "completed"
    CandidateArchive(context.workspace, requested_strategy="population", read_only=True).validate_candidate_integrity(
        require_all=True,
    )


def test_transaction_links_formal_native_execution_receipt(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-with-receipt"
    _batch_directory(context.workspace, journal_id)
    receipt = _formal_execution_receipt(journal_id=journal_id)
    receipt_path = context.workspace / "evolution" / "producer-batches" / journal_id / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
        native_execution_receipt_sha256=receipt["receipt_sha256"],
    )

    assert result.publication_status == "published"
    assert result.journal.native_execution_receipt_sha256 == receipt["receipt_sha256"]
    persisted = json.loads(
        (context.workspace / "evolution" / "producer-batches" / journal_id / "journal.json").read_bytes()
    )
    assert persisted["native_execution_receipt_sha256"] == receipt["receipt_sha256"]


def test_transaction_links_durable_python_handoff_to_formal_receipt_and_plan(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-with-python-handoff"
    _batch_directory(context.workspace, journal_id)
    receipt = _formal_execution_receipt(journal_id=journal_id)
    receipt_path = context.workspace / "evolution" / "producer-batches" / journal_id / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    digest = "a" * 64
    handoff = build_python_producer_admission_handoff(
        run_id=journal_id,
        journal_id=journal_id,
        parent_task_id="producer",
        task_id="native-bundle-publication",
        binding_sha256=digest,
        sidecar_raw_sha256=digest,
        sidecar_pin_sha256=digest,
        launch_intent_sha256=digest,
        attestation_sha256=digest,
        runtime_manifest_sha256=digest,
        runtime_tree_sha256=digest,
        executable_owner_sha256=digest,
        native_execution_receipt_sha256=receipt["receipt_sha256"],
        terminal_sha256=digest,
        runtime_observation_sha256=digest,
        broker_transcript_sha256=digest,
        envelope_sha256=digest,
        materials_sha256=digest,
        contract_sha256=plan.contract_sha256,
        evaluator_sha256=plan.evaluator_fingerprint,
        runner_sha256=plan.runner_fingerprint,
        dependency_sha256=plan.dependency_sha256,
        environment_sha256=plan.environment_sha256,
        admission_plan_sha256=plan.digest(),
        request_budget=10,
        wall_timeout_seconds=60.0,
        deadline_unix=4102444800.0,
    )
    persist_python_producer_admission_handoff(
        context.workspace / "evolution" / "producer-batches" / journal_id,
        handoff=handoff,
    )

    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
        native_execution_receipt_sha256=receipt["receipt_sha256"],
        python_handoff_sha256=handoff.handoff_sha256,
    )

    assert result.publication_status == "published"
    assert result.journal.python_handoff_sha256 == handoff.handoff_sha256
    persisted = json.loads(
        (context.workspace / "evolution" / "producer-batches" / journal_id / "journal.json").read_bytes()
    )
    assert persisted["python_handoff_sha256"] == handoff.handoff_sha256
    handoff_path = context.workspace / "evolution" / "producer-batches" / journal_id / "python-producer-admission-handoff.json"
    handoff_path.unlink()
    with pytest.raises(ProducerBundleRecoveryError, match="python_handoff_invalid"):
        resume_producer_bundle_publication(context.workspace, plan, result.published_journal)


def test_transaction_rejects_python_handoff_digest_without_durable_matching_record(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-missing-python-handoff"
    _batch_directory(context.workspace, journal_id)
    receipt = _formal_execution_receipt(journal_id=journal_id)
    receipt_path = context.workspace / "evolution" / "producer-batches" / journal_id / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(NativeProducerBundleTransactionError) as failure:
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
            native_execution_receipt_sha256=receipt["receipt_sha256"],
            python_handoff_sha256="a" * 64,
        )
    assert failure.value.code == "producer_bundle_transaction_python_handoff_invalid"
    assert not (context.workspace / "evolution" / "producer-batches" / journal_id / "journal.prepared.json").exists()


def test_transaction_rechecks_python_handoff_after_pipeline_guard_before_evaluator(
    tmp_path: Path, monkeypatch,
) -> None:
    """A pipeline-owned timeout callback cannot bypass the handoff gate before evaluation."""
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-pipeline-handoff-guard"
    _batch_directory(context.workspace, journal_id)
    receipt = _formal_execution_receipt(journal_id=journal_id)
    receipt_path = context.workspace / "evolution" / "producer-batches" / journal_id / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    digest = "a" * 64
    handoff = build_python_producer_admission_handoff(
        run_id=journal_id,
        journal_id=journal_id,
        parent_task_id="producer",
        task_id="native-bundle-publication",
        binding_sha256=digest,
        sidecar_raw_sha256=digest,
        sidecar_pin_sha256=digest,
        launch_intent_sha256=digest,
        attestation_sha256=digest,
        runtime_manifest_sha256=digest,
        runtime_tree_sha256=digest,
        executable_owner_sha256=digest,
        native_execution_receipt_sha256=receipt["receipt_sha256"],
        terminal_sha256=digest,
        runtime_observation_sha256=digest,
        broker_transcript_sha256=digest,
        envelope_sha256=digest,
        materials_sha256=digest,
        contract_sha256=plan.contract_sha256,
        evaluator_sha256=plan.evaluator_fingerprint,
        runner_sha256=plan.runner_fingerprint,
        dependency_sha256=plan.dependency_sha256,
        environment_sha256=plan.environment_sha256,
        admission_plan_sha256=plan.digest(),
        request_budget=10,
        wall_timeout_seconds=60.0,
        deadline_unix=4102444800.0,
    )
    persist_python_producer_admission_handoff(
        context.workspace / "evolution" / "producer-batches" / journal_id,
        handoff=handoff,
    )
    handoff_path = (
        context.workspace / "evolution" / "producer-batches" / journal_id
        / "python-producer-admission-handoff.json"
    )

    armed = False

    def pipeline_guard() -> None:
        if armed and handoff_path.exists():
            handoff_path.unlink()

    pipeline = context.bundle_pipeline
    pipeline.set_continuation_guard(pipeline_guard)
    original_effective_timeout = pipeline._effective_timeout

    def effective_timeout(stage: str) -> float:
        nonlocal armed
        if stage == "candidate_execution":
            armed = True
        try:
            return original_effective_timeout(stage)
        finally:
            armed = False

    monkeypatch.setattr(pipeline, "_effective_timeout", effective_timeout)
    evaluated: list[bool] = []
    original_evaluate = bundle_evolution.evaluate_candidate_execution

    def observe_evaluator(*args, **kwargs):
        evaluated.append(True)
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", observe_evaluator)
    with pytest.raises(NativeProducerBundleTransactionError, match="python_handoff_invalid"):
        run_native_producer_bundle_publication_transaction(
            context.workspace,
            strategy,
            drafts,
            plan,
            journal_id=journal_id,
            native_execution_receipt_sha256=receipt["receipt_sha256"],
            python_handoff_sha256=handoff.handoff_sha256,
        )
    assert evaluated == []


@pytest.mark.parametrize("mode", ["missing", "invalid", "tampered", "unknown-field"])
def test_transaction_rejects_missing_invalid_or_tampered_formal_receipt(
    tmp_path: Path, mode: str,
) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = f"transaction-receipt-{mode}"
    _batch_directory(context.workspace, journal_id)
    receipt = _formal_execution_receipt(journal_id=journal_id)
    receipt_path = context.workspace / "evolution" / "producer-batches" / journal_id / "execution-receipt.json"
    if mode == "invalid":
        receipt_path.write_text("{}", encoding="utf-8")
    elif mode == "tampered":
        receipt["status"] = "failed"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    elif mode == "unknown-field":
        receipt["unexpected"] = True
        receipt["receipt_sha256"] = _digest_without(receipt, "receipt_sha256")
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(NativeProducerBundleTransactionError) as failure:
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
            native_execution_receipt_sha256=receipt["receipt_sha256"],
        )
    assert failure.value.code == "producer_bundle_transaction_execution_receipt_invalid"
    assert not (context.workspace / "evolution" / "producer-batches" / journal_id / "journal.prepared.json").exists()


def test_all_rejected_shinka_batch_leaves_native_archive_and_state_unchanged(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (999, 999))
    journal_id = "transaction-all-rejected"
    _batch_directory(context.workspace, journal_id)
    archive_before, state_before, records_before = _archive_projection(context.workspace)

    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )

    assert [item.report.validity for item in result.evaluations] == [0, 0]
    assert result.admitted_candidate_ids == ()
    assert len(result.rejected_candidate_ids) == 2
    assert result.publication_status == "all_rejected"
    assert result.artifacts == ()
    assert result.manifest is None
    assert result.published_journal is None
    archive_after, state_after, records_after = _archive_projection(context.workspace)
    assert (archive_after, state_after, records_after) == (archive_before, state_before, records_before)
    assert not (context.workspace / "evolution" / "producer-publication.json").exists()
    assert result.terminal_journal is not None
    terminal = json.loads((
        context.workspace / "evolution" / "producer-batches" / journal_id / "journal.json"
    ).read_bytes())
    assert terminal["state"] == "all_rejected"
    assert terminal["archive_after_sha256"] == terminal["base_archive_sha256"]


def test_evolved_population_is_rejected_before_draft_evaluation_or_publication(tmp_path: Path) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    initial = strategy.run()
    assert initial.status == "completed"
    _strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "transaction-evolved-state"
    _batch_directory(context.workspace, journal_id)
    archive_before, state_before, records_before = _archive_projection(context.workspace)

    from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError

    try:
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
        )
    except NativeProducerBundleTransactionError as exc:
        assert getattr(exc, "code", None) == "producer_bundle_transaction_population_history_unsupported"
    else:
        raise AssertionError("evolved population history must not be rewritten as iteration zero")

    archive_after, state_after, records_after = _archive_projection(context.workspace)
    assert (archive_after, state_after, records_after) == (archive_before, state_before, records_before)
    assert not (
        context.workspace / "evolution" / "producer-batches" / journal_id / "journal.json"
    ).exists()


@pytest.mark.parametrize("changed", ["max_rounds", "generator_fingerprint"])
def test_transaction_rejects_live_strategy_configuration_drift_before_evaluation(tmp_path: Path, changed: str) -> None:
    context = build_context(tmp_path / "native")
    strategy = PopulationStrategy(context)
    _initialize_native_population(strategy)
    _strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    updates = {changed: 2 if changed == "max_rounds" else "e" * 64}
    drifted = PopulationStrategy(replace(context, config=replace(context.config, **updates)))
    journal_id = "transaction-config-drift"
    _batch_directory(context.workspace, journal_id)
    archive_before, state_before, records_before = _archive_projection(context.workspace)

    from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError

    try:
        run_native_producer_bundle_publication_transaction(
            context.workspace, drifted, drafts, plan, journal_id=journal_id,
        )
    except NativeProducerBundleTransactionError as exc:
        assert exc.code == "producer_bundle_transaction_state_invalid"
    else:
        raise AssertionError("live strategy configuration drift must fail before evaluation")

    assert _archive_projection(context.workspace) == (archive_before, state_before, records_before)
    assert not (context.workspace / "evolution/producer-batches" / journal_id / "native-drafts").exists()


@pytest.mark.parametrize("changed", ["producer_id", "source"])
def test_transaction_revalidates_all_drafts_before_first_execution(tmp_path, monkeypatch, changed):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9, 8))
    _batch_directory(context.workspace, "mutated-batch")
    before = _archive_projection(context.workspace)
    if changed == "source":
        drafts[1].draft.source_files[drafts[1].draft.filename] += "\n# changed\n"
    else:
        drafts[1].draft.metadata["producer_bundle"]["producer_id"] = "forged-source"
    monkeypatch.setattr(context.bundle_pipeline, "evaluate_draft_non_publishing",
                        lambda *a, **k: pytest.fail("mutated batch reached execution"))
    with pytest.raises(NativeProducerBundleTransactionError, match="drafts_invalid"):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id="mutated-batch",
        )
    assert _archive_projection(context.workspace) == before


def test_valid_lower_scoring_import_is_archived_without_displacing_elite(tmp_path):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (0,))
    _batch_directory(context.workspace, "lower-score")
    before = strategy.archive.read_state()
    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id="lower-score",
    )
    assert result.publication_status == "published"
    assert len(result.admitted_candidate_ids) == 1
    state = strategy.archive.read_state()
    assert state["active_ids"] == before["active_ids"]
    assert state["best_candidate_id"] == before["best_candidate_id"]
    assert result.admitted_candidate_ids[0] in {item.candidate_id for item in strategy.archive.records()}
    assert strategy.resume().status == "completed"


def _interrupt_before_stage(tmp_path, monkeypatch):
    context = build_context(tmp_path / "native")
    _initialize_native_population(PopulationStrategy(context))
    strategy, drafts, plan, _export = _shinka_drafts(tmp_path, context, (9,))
    journal_id = "interrupted-intent"
    _batch_directory(context.workspace, journal_id)
    before = _archive_projection(context.workspace)
    stage = producer_bundle_transaction.stage_producer_bundle_publication

    def interrupt(*args, **kwargs):
        raise RuntimeError("simulated interruption before staging")

    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", interrupt)
    with pytest.raises(NativeProducerBundleTransactionError, match="recovery_required"):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
        )
    assert _archive_projection(context.workspace) == before
    monkeypatch.setattr(producer_bundle_transaction, "stage_producer_bundle_publication", stage)
    for name in ("run_candidate_execution_recorded", "evaluate_candidate_execution"):
        monkeypatch.setattr(bundle_evolution, name, lambda *a, **k: pytest.fail("completed draft replayed"))
    return context, strategy, drafts, plan, journal_id, before


def test_interrupted_transaction_pins_intent_and_exact_retry_reuses_completed_evidence(tmp_path, monkeypatch):
    context, strategy, drafts, plan, journal_id, before = _interrupt_before_stage(tmp_path, monkeypatch)
    batch = context.workspace / "evolution/producer-batches" / journal_id
    intent_path = batch / "journal.prepared.json"
    original = intent_path.read_bytes()
    original_inode = intent_path.stat().st_ino
    intent = json.loads(original)
    assert intent["state"] == "prepared"
    bindings = list((batch / "native-drafts").glob("*/draft-binding.json"))
    assert len(bindings) == 1
    assert json.loads(bindings[0].read_bytes())["journal_sha256"]
    for field, value in (("run_id", "changed-run"), ("parent_task_id", "changed-parent"),
                         ("task_id", "changed-task"), ("budget_sha256", "f" * 64)):
        code = "budget_mismatch" if field == "budget_sha256" else "prepared_intent_mismatch"
        with pytest.raises(NativeProducerBundleTransactionError, match=code):
            run_native_producer_bundle_publication_transaction(
                context.workspace, strategy, drafts, plan, journal_id=journal_id, **{field: value},
            )
        assert _archive_projection(context.workspace) == before
        assert intent_path.read_bytes() == original
        assert intent_path.stat().st_ino == original_inode
        assert not (batch / "stage").exists()

    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )
    assert result.publication_status == "published"
    assert len(result.admitted_candidate_ids) == 1
    assert intent_path.read_bytes() == original
    assert intent_path.stat().st_ino == original_inode
    assert result.evaluations[0].journal_sha256 == result.journal.digest()


@pytest.mark.parametrize("change", ["delete", "tamper"])
def test_interrupted_transaction_rejects_missing_or_changed_prepared_intent(tmp_path, monkeypatch, change):
    context, strategy, drafts, plan, journal_id, before = _interrupt_before_stage(tmp_path, monkeypatch)
    intent_path = context.workspace / "evolution/producer-batches" / journal_id / "journal.prepared.json"
    if change == "delete":
        intent_path.unlink()
    else:
        value = json.loads(intent_path.read_bytes())
        value["task_id"] = "tampered-task"
        intent_path.write_text(json.dumps(value))
    with pytest.raises(NativeProducerBundleTransactionError, match="prepared_intent"):
        run_native_producer_bundle_publication_transaction(
            context.workspace, strategy, drafts, plan, journal_id=journal_id,
        )
    assert _archive_projection(context.workspace) == before
