"""Controller-bound publication gates over inert, already-pinned local evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_bundle_population import build_context
from test_producer_bundle_recovery import _journal, _plan
from test_python_producer_recovery_anchor import _durable_snapshot
from test_rsi_python_admission import DIGEST, OTHER, _files, _register, _rows, _setup
from test_rsi_python_admission_flow import _forged_checkpoint_append, _lose_record, _pin

from lunar_evolution import bundle_evolution, producer_bundle_rejection, producer_process
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_python_publication as publication
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.evolution import (
    CandidateArchive,
    CandidateDraft,
    CandidateIntegrityAuthority,
    PopulationStrategy,
)
from lunar_evolution.producer_bundle_admission import build_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_control import native_producer_bundle_budget_sha256
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_population import ProducerBundleDraft
from lunar_evolution.producer_bundle_preflight import (
    derive_producer_bundle_candidate_id,
    preflight_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.producer_bundle_receipts import _collect_retained_evidence
from lunar_evolution.producer_bundle_staging import (
    ProducerBundlePublicationArtifact,
    commit_producer_bundle_publication,
    stage_producer_bundle_publication,
)
from lunar_evolution.python_producer_admission_anchor import (
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)


def _fixture(tmp_path, *, strategy=False, pin=True, complete_transaction=False, execution_control=None):
    value = _setup(tmp_path)
    plan = replace(
        _plan(), contract_sha256=value.binding.contract_sha256, evaluator_kind="local",
        evaluator_fingerprint=value.binding.evaluator_fingerprint,
        runner_fingerprint=value.binding.intent.runner_fingerprint,
        dependency_sha256=value.binding.dependency_sha256,
        environment_sha256=value.binding.environment_sha256,
    )
    if complete_transaction:
        draft = CandidateDraft.from_files({"main.py": "# Inert source; never executed.\n"}, entrypoint="main.py")
        bundle_sha256 = bundle_evolution.validate_bundle_draft(draft, plan.contract_sha256).digest()
        draft = replace(draft, metadata={"producer_bundle": {
            "bundle_id": "bundle-1", "bundle_sha256": bundle_sha256,
            "producer_fingerprint": OTHER, "producer_id": None, "envelope_sha256": None,
        }})
        value.drafts = (ProducerBundleDraft("bundle-1", draft, bundle_sha256, OTHER),)
        plan = build_producer_bundle_admission_plan(value.drafts, **{
            field: getattr(plan, field) for field in (
                "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
                "dependency_sha256", "environment_sha256",
            )
        })
    state = {
        "strategy": "population", "config": {"strategy": "population", "num_islands": 1},
        "active_ids": {"0": []},
    }
    evolution = value.workspace / "evolution"
    (evolution / "candidates").mkdir()
    (evolution / "archive.jsonl").write_bytes(b"")
    budget_sha256 = _journal(plan).budget_sha256
    if strategy:
        # Context construction only writes fixture inputs; never initialize a population.
        context = replace(build_context(tmp_path / "context"), workspace=value.workspace)
        value.strategy = object.__new__(PopulationStrategy)
        value.strategy.context = context
        value.strategy._cancelled = lambda: False
        value.strategy._check_stage = lambda stage: None
        budget_sha256 = native_producer_bundle_budget_sha256(value.strategy, execution_control)
        if complete_transaction:
            value.strategy.config = context.config
            value.strategy.integrity_authority = CandidateIntegrityAuthority(schema_version="1", generator_fingerprint=DIGEST, **{
                field: getattr(plan, field) for field in (
                    "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
                    "dependency_sha256", "environment_sha256",
                )
            })
            state.update(iteration=0, status="running",
                         candidate_integrity_authority=value.strategy.integrity_authority.to_dict())
            value.strategy.archive = CandidateArchive(value.workspace, requested_strategy="population", read_only=True)
            value.strategy._load_state = lambda: json.loads((evolution / "state.json").read_bytes())
            # This fixture tests transaction composition, not population state semantics.
            value.strategy._validate_candidate_integrity_state = lambda state: None
            value.strategy._active = lambda state: []
    state_bytes = json.dumps(state, sort_keys=True).encode()
    (evolution / "state.json").write_bytes(state_bytes)
    handoff_payload = value.handoff.to_dict()
    handoff_payload.pop("handoff_sha256")
    handoff_payload["admission_plan_sha256"] = plan.digest()
    handoff = build_python_producer_admission_handoff(handoff_payload)
    (value.batch / "python-producer-admission-handoff.json").unlink()
    pinned = persist_python_producer_admission_handoff_pinned(value.batch, handoff=handoff)
    journal = replace(
        _journal(plan, state="prepared"), budget_sha256=budget_sha256,
        native_execution_receipt_sha256=DIGEST, python_handoff_sha256=handoff.handoff_sha256,
        python_handoff_file_pin=pinned.file_pin, journal_sha256=None,
    )
    if complete_transaction:
        item = plan.bundles[0]
        candidate = replace(
            journal.candidates[0], bundle_sha256=item.bundle_sha256,
            candidate_id=derive_producer_bundle_candidate_id(journal.journal_id, 0, item.bundle_id, item.bundle_sha256),
            preparation_receipt_sha256=transaction._sha(transaction._canonical({
                "plan_sha256": plan.digest(), "bundle_id": item.bundle_id, "ordinal": 0,
            })),
        )
        journal = replace(
            journal, candidates=(candidate,), base_state_sha256=hashlib.sha256(state_bytes).hexdigest(),
            archive_prefix_sha256=transaction._state_prefix(value.workspace, b"", state_bytes, state),
            journal_sha256=None,
        )
    (value.batch / "journal.prepared.json").write_bytes(_intent_content(journal)[0])
    (value.batch / "journal.prepared.json").chmod(0o600)
    (value.batch / "python-producer-admission-anchor.json").unlink()
    anchor = project_python_producer_admission_attempt_anchor(handoff)
    persist_python_producer_admission_attempt_anchor(value.batch, anchor=anchor)
    value.handoff, value.pin, value.journal, value.anchor = handoff, pinned.file_pin, journal, anchor
    value.admission_plan, value.base_state = plan, state
    value.record = _pin(value) if pin else _register(value)
    assert value.record.production_admission is False
    return value


@pytest.fixture(autouse=True)
def _no_process_or_evaluator(monkeypatch):
    effects = {"process": 0, "evaluator": 0}

    def forbid(effect):
        def fail(*args, **kwargs):
            effects[effect] += 1
            pytest.fail(f"inert publication test reached {effect}")
        return fail

    monkeypatch.setattr(subprocess, "Popen", forbid("process"))
    monkeypatch.setattr(subprocess, "run", forbid("process"))
    monkeypatch.setattr(producer_process, "run_producer_process", forbid("process"))
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbid("evaluator"))
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing",
        forbid("evaluator"),
    )
    yield effects
    assert effects == {"process": 0, "evaluator": 0}


def _call(value, operation="resume", *, plan=None, digest=None, **kwargs):
    arguments = {"expected_admission_record_sha256": digest or value.record.record_sha256}
    if operation == "run":
        return publication.run_rsi_python_bundle_publication(
            value.controller, value.binding.run_id, value.episode_id,
            getattr(value, "strategy", None), kwargs.pop("drafts", ()), plan or value.admission_plan,
            **arguments, **kwargs,
        )
    return publication.resume_rsi_python_bundle_publication(
        value.controller, value.binding.run_id, value.episode_id,
        plan or value.admission_plan, **arguments,
    )


def _publish_files(value):
    """Run real preflight, stage and commit on retained bytes, without an evaluator."""
    candidate = value.journal.candidates[0]
    binding_path = value.batch / "native-drafts" / candidate.candidate_id / "draft-binding.json"
    binding_path.parent.mkdir(parents=True)
    binding = {
        "protocol": "lunar-native-draft-binding-v1", "journal_sha256": value.journal.digest(),
        "journal_id": value.journal.journal_id, "ordinal": 0,
        **{field: getattr(candidate, field) for field in (
            "candidate_id", "bundle_id", "bundle_sha256", "parent_id",
            "generation", "iteration", "island_id",
        )},
    }
    binding_path.write_bytes(json.dumps(binding, sort_keys=True).encode())
    evidence = _collect_retained_evidence(
        value.workspace, (value.batch / "journal.prepared.json", binding_path),
    )
    artifact = ProducerBundlePublicationArtifact(
        candidate.candidate_id, {"main.py": b"# Inert retained source; never executed.\n"},
        {"candidate_id": candidate.candidate_id}, {"receipt_sha256": "d" * 64},
        execution_receipt_sha256="c" * 64, evaluation_receipt_sha256="e" * 64,
        retained_evidence=evidence,
    )
    preflight = preflight_producer_bundle_publication(
        value.workspace, value.admission_plan, value.journal,
    )
    stage_producer_bundle_publication(
        value.workspace, value.journal, preflight, (artifact,),
        state_after={**value.base_state, "active_ids": {"0": [candidate.candidate_id]}},
    )
    staged = parse_producer_bundle_publication_journal(value.batch / "journal.json")
    published = commit_producer_bundle_publication(value.workspace, staged)
    assert published.state == "published"
    return published


def _forbid_lower_calls(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("entry refusal reached transaction or recovery")
    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", fail)
    monkeypatch.setattr(publication, "resume_producer_bundle_publication", fail)


def _replace_same_bytes(path):
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(path.stat().st_mode & 0o777)
    replacement.replace(path)


def test_real_published_projection_recovers_from_original_controller_pin_readonly(tmp_path):
    value = _fixture(tmp_path)
    original = value.ledger.controller_checkpoint(value.binding.run_id)
    published = _publish_files(value)
    assert published.digest() != value.journal.digest()
    rows, files = _rows(value), _files(value)
    result = _call(value)
    assert result.status == "published"
    assert result.candidate_ids == (value.journal.candidates[0].candidate_id,)
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.ledger.controller_checkpoint(value.binding.run_id) == original
    assert value.gateway.calls == 1


@pytest.mark.parametrize("operation", ["run", "resume"])
@pytest.mark.parametrize("mutation", [
    "row_missing", "row_replaced", "reference_missing", "reference_replaced",
    "wrong_digest", "wrong_plan", "sidecar_replaced", "handoff_missing",
    "handoff_replaced", "prepared_drift", "anchor_drift",
])
def test_entry_refusal_is_readonly_and_never_calls_lower_pipeline(
    tmp_path, monkeypatch, operation, mutation,
):
    value = _fixture(tmp_path)
    plan, digest = value.admission_plan, value.record.record_sha256
    if mutation.startswith("row"):
        _lose_record(value, value.record, "missing" if mutation == "row_missing" else "replaced")
    elif mutation == "reference_missing":
        _forged_checkpoint_append(value, lambda state: state.pop("python_admission_refs"))
    elif mutation == "reference_replaced":
        _forged_checkpoint_append(
            value, lambda state: state["python_admission_refs"][value.episode_id].update(
                record_sha256=OTHER,
            ),
        )
    elif mutation == "wrong_digest":
        digest = OTHER
    elif mutation == "wrong_plan":
        plan = replace(plan, environment_sha256=OTHER)
    else:
        paths = {
            "sidecar_replaced": value.batch / "python-producer-binding.json",
            "handoff_missing": value.batch / "python-producer-admission-handoff.json",
            "handoff_replaced": value.batch / "python-producer-admission-handoff.json",
            "prepared_drift": value.batch / "journal.prepared.json",
            "anchor_drift": value.batch / "python-producer-admission-anchor.json",
        }
        path = paths[mutation]
        if mutation == "handoff_missing":
            path.unlink()
        elif mutation.endswith("drift"):
            path.write_bytes(path.read_bytes() + b"\n# altered durable evidence\n")
        else:
            _replace_same_bytes(path)
    _forbid_lower_calls(monkeypatch)
    rows, files = _rows(value), _files(value)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, operation, plan=plan, digest=digest)
    expected = {
        "wrong_digest": "record_identity_mismatch", "wrong_plan": "plan_mismatch",
    }.get(mutation, "evidence_invalid")
    assert caught.value.code == "rsi_python_publication_" + expected
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == 1


def test_run_forwards_only_original_identity_and_always_installs_evidence_gate(tmp_path, monkeypatch):
    value = _fixture(tmp_path)
    rows, files = _rows(value), _files(value)
    sentinel = SimpleNamespace(publication_status="inert-spy")
    calls = []

    def transaction_spy(workspace, strategy, drafts, plan, **kwargs):
        calls.append((workspace, strategy, drafts, plan, kwargs))
        assert kwargs["continuation_guard"] is None
        kwargs["evidence_revalidator"]("inert-spy-boundary")
        return sentinel

    monkeypatch.setattr(publication, "run_native_producer_bundle_publication_transaction", transaction_spy)
    assert _call(value, "run") is sentinel
    assert len(calls) == 1
    workspace, _, _, plan, kwargs = calls[0]
    assert workspace == value.workspace
    assert plan.to_dict() == value.admission_plan.to_dict()
    for field in (
        "journal_id", "run_id", "parent_task_id", "task_id", "budget_sha256",
        "native_execution_receipt_sha256", "python_handoff_sha256", "python_handoff_file_pin",
    ):
        assert kwargs[field] == getattr(value.journal, field)
    assert _rows(value) == rows
    assert _files(value) == files


@pytest.mark.parametrize("mutation", ["row", "reference", "ledger", "workspace"])
def test_actual_run_revalidates_after_initial_caller_checkpoint(tmp_path, monkeypatch, mutation):
    value = _fixture(tmp_path, strategy=True)
    observed = []
    after_callback = []

    def guard(stage):
        observed.append(stage)
        if mutation == "row":
            _lose_record(value, value.record, "missing")
        elif mutation == "reference":
            _forged_checkpoint_append(value, lambda state: state.pop("python_admission_refs"))
        elif mutation == "ledger":
            value.controller.ledger = None
        else:
            value.controller.producer_workspace = tmp_path / "foreign-workspace"
        after_callback.append((_rows(value), _files(value)))

    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, "run", continuation_guard=guard)
    assert observed == ["producer_preparation"]
    expected = "controller_drift" if mutation in {"ledger", "workspace"} else "evidence_invalid"
    assert caught.value.code == "rsi_python_publication_" + expected
    assert (_rows(value), _files(value)) == after_callback[0]
    assert value.gateway.calls == 1


@pytest.mark.parametrize("operation", ["run", "resume"])
def test_final_return_drift_refuses_success_without_rolling_back_real_published_files(
    tmp_path, monkeypatch, operation,
):
    value = _fixture(tmp_path)
    durable = []
    original_resume = publication.resume_producer_bundle_publication

    def lower(*args, **kwargs):
        _publish_files(value)
        result = original_resume(value.workspace, value.admission_plan, value.journal)
        assert result.status == "published"
        _lose_record(value, value.record, "missing")
        durable.append((_rows(value), _files(value)))
        return result

    name = ("run_native_producer_bundle_publication_transaction" if operation == "run"
            else "resume_producer_bundle_publication")
    monkeypatch.setattr(publication, name, lower)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, operation)
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert (_rows(value), _files(value)) == durable[0]
    assert parse_producer_bundle_publication_journal(value.batch / "journal.json").state == "published"
    assert value.gateway.calls == 1


@pytest.mark.parametrize("operation", ["run", "resume"])
def test_legacy_row_without_explicit_checkpoint_pin_is_not_adopted(tmp_path, monkeypatch, operation):
    value = _fixture(tmp_path, pin=False)
    _forbid_lower_calls(monkeypatch)
    rows, files = _rows(value), _files(value)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, operation)
    assert caught.value.code == "rsi_python_publication_reference_missing"
    assert (_rows(value), _files(value)) == (rows, files)


@pytest.mark.parametrize("operation", ["run", "resume"])
@pytest.mark.parametrize("mutation", ["missing", "symlink", "directory"])
def test_invalid_database_is_refused_before_connector_without_creating_evidence(
    tmp_path, monkeypatch, operation, mutation,
):
    value = _fixture(tmp_path)
    database = value.ledger.database
    if mutation == "symlink":
        target = tmp_path / "retained-database.sqlite3"
        target.write_bytes(database.read_bytes())
    database.unlink()
    if mutation == "symlink":
        database.symlink_to(target)
    elif mutation == "directory":
        database.mkdir()
    before = _durable_snapshot(value.workspace)
    _forbid_lower_calls(monkeypatch)

    def forbidden_connector():
        pytest.fail("invalid database reached a creating connector")
    monkeypatch.setattr(value.ledger, "_connect", forbidden_connector)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, operation)
    expected = "evidence_invalid" if mutation == "missing" else "ledger_invalid"
    assert caught.value.code == "rsi_python_publication_" + expected
    assert _durable_snapshot(value.workspace) == before
    if mutation == "missing":
        assert not database.exists()


def test_actual_run_callback_database_removal_does_not_recreate_it(tmp_path, monkeypatch):
    value = _fixture(tmp_path, strategy=True)
    observed = []
    durable = []

    def guard(stage):
        observed.append(stage)
        value.ledger.database.unlink()
        durable.append(_durable_snapshot(value.workspace))
        monkeypatch.setattr(value.ledger, "_connect", lambda: pytest.fail("removed DB was reconnected"))

    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, "run", continuation_guard=guard)
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert observed == ["producer_preparation"]
    assert not value.ledger.database.exists()
    assert _durable_snapshot(value.workspace) == durable[0]


def test_actual_numeric_timeout_callback_row_drift_refuses_before_evaluation(tmp_path, monkeypatch):
    value = _fixture(tmp_path, strategy=True)
    pipeline = value.strategy.context.bundle_pipeline
    calls, durable = [], []

    def numeric_timeout(stage):
        calls.append(stage)
        if stage == "inert_numeric_timeout":
            _lose_record(value, value.record, "missing")
            durable.append((_rows(value), _files(value)))
        return 3.0

    pipeline.set_remaining_timeout(numeric_timeout)
    original_read_state = transaction._read_state

    def numeric_boundary(root):
        # Exercise the real installed timeout wrapper before any candidate/evaluator I/O.
        pipeline._remaining_timeout("inert_numeric_timeout")
        return original_read_state(root)

    # Original inert RSI fixtures do not contain a native process receipt or actual draft.
    # Only these source seams are isolated; public control and handoff/evidence gates are real.
    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    monkeypatch.setattr(transaction, "_snapshot_drafts", lambda drafts, plan: drafts)
    monkeypatch.setattr(transaction, "_read_state", numeric_boundary)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, "run", drafts=(object(),))
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert calls == ["producer_preparation", "inert_numeric_timeout"]
    assert (_rows(value), _files(value)) == durable[0]
    assert pipeline._remaining_timeout is numeric_timeout
    assert value.gateway.calls == 1


@pytest.mark.parametrize(("boundary", "authority"), [
    ("preparation", "strategy"), ("timeout", "strategy"), ("commit", "strategy"),
    ("preparation", "control"), ("timeout", "control"),
])
def test_cancellation_predicate_row_loss_is_checked_before_admitting_work(
    tmp_path, monkeypatch, boundary, authority,
):
    active = boundary == "preparation"
    cancellation_calls = []
    durable = []
    admitted = []
    control = (SolveExecutionControl(30.0, clock=lambda: 100.0, cancelled=lambda: cancelled())
               if authority == "control" else None)
    value = _fixture(
        tmp_path, strategy=True, complete_transaction=boundary == "commit", execution_control=control,
    )
    pipeline = value.strategy.context.bundle_pipeline

    def cancelled():
        if active:
            cancellation_calls.append(boundary)
            # The ordinary checkpoint samples cancellation first. Numeric timeout
            # binding samples twice before its final observation. Remove the row on
            # the last caller predicate immediately before the mandatory evidence gate.
            target = 3 if boundary == "timeout" or authority == "control" else 2
            if len(cancellation_calls) == target:
                _lose_record(value, value.record, "missing")
                durable.append((_rows(value), _files(value)))
        return False

    if authority == "strategy":
        value.strategy._cancelled = cancelled
    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    original_read_state = transaction._read_state

    def read_state(root):
        nonlocal active
        if boundary == "preparation":
            admitted.append("preparation")
            pytest.fail("removed row reached transaction preparation")
        if boundary == "timeout":
            active = True
            pipeline._remaining_timeout("inert_cancellation_timeout")
            admitted.append("timeout")
            pytest.fail("removed row admitted positive evaluator timeout")
        return original_read_state(root)

    monkeypatch.setattr(transaction, "_read_state", read_state)
    if boundary != "commit":
        monkeypatch.setattr(transaction, "_snapshot_drafts", lambda drafts, plan: drafts)
        drafts = (object(),)
    else:
        candidate = value.journal.candidates[0]
        result = SimpleNamespace(candidate_id=candidate.candidate_id, report=SimpleNamespace(validity=1))
        artifact = SimpleNamespace(candidate_id=candidate.candidate_id)
        monkeypatch.setattr(pipeline, "evaluate_draft_non_publishing", lambda *a, **k: result)
        monkeypatch.setattr(transaction, "build_native_producer_bundle_publication_artifact", lambda *a, **k: artifact)
        monkeypatch.setattr(transaction, "derive_population_state_after", lambda *a, **k: value.base_state)
        monkeypatch.setattr(transaction, "stage_producer_bundle_publication", lambda *a, **k: None)
        original_parse = transaction.parse_producer_bundle_publication_journal
        monkeypatch.setattr(transaction, "parse_producer_bundle_publication_journal", lambda source: (
            value.journal if source == value.batch / "journal.json" else original_parse(source)
        ))

        def commit_boundary(workspace, journal, *, checkpoint):
            nonlocal active
            active = True
            # Exercise the actual composed callback passed into the commit critical
            # boundary, without moving any candidate or writing an unknown marker.
            checkpoint("producer_commit_verified")
            admitted.append("commit")
            pytest.fail("removed row passed the final pre-commit checkpoint")

        monkeypatch.setattr(transaction, "commit_producer_bundle_publication", commit_boundary)
        drafts = value.drafts

    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, "run", drafts=drafts, execution_control=control)
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert len(cancellation_calls) == (3 if boundary == "timeout" or authority == "control" else 2)
    assert len(durable) == 1
    assert admitted == []
    assert (_rows(value), _files(value)) == durable[0]
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()
    assert pipeline._remaining_timeout is None


@pytest.mark.parametrize("terminal_drift", [False, True])
def test_actual_transaction_reuses_prepared_intent_and_inspects_terminal_with_inert_receipt_seam(
    tmp_path, monkeypatch, terminal_drift,
):
    value = _fixture(tmp_path, strategy=True, complete_transaction=True)
    candidate = value.journal.candidates[0]
    inert_receipts = {
        "candidate_id": candidate.candidate_id,
        "execution_receipt": {"fixture": "inert-execution"},
        "evaluation_receipt": {"fixture": "inert-rejection"},
        "retained_evidence": {"fixture": "inert-evidence", "evidence_sha256": "f" * 64},
    }
    verifications = []

    def receipt_witness(root, journal, item, receipt):
        assert root == value.workspace
        assert journal == value.journal
        assert item == candidate
        assert receipt == inert_receipts
        verifications.append(item.candidate_id)
        return "c" * 64, "e" * 64

    # Keep actual prepared/preflight/terminal files, inode descriptors, checkpoint gates and
    # read-only inspection. Native process/solver receipt validation is a pure fixture seam.
    monkeypatch.setattr(producer_bundle_rejection, "_verify_receipts", receipt_witness)
    monkeypatch.setattr(
        producer_bundle_rejection, "build_native_producer_bundle_publication_artifact",
        lambda *a, **k: SimpleNamespace(**{
            key: value for key, value in inert_receipts.items() if key != "candidate_id"
        }),
    )
    preflight = preflight_producer_bundle_publication(value.workspace, value.admission_plan, value.journal)
    terminal = producer_bundle_rejection.finalize_producer_bundle_all_rejected(
        value.workspace, value.journal, preflight,
        (SimpleNamespace(candidate_id=candidate.candidate_id, ordinal=0,
                         journal_sha256=value.journal.digest(), report=SimpleNamespace(validity=0)),),
        authority=value.strategy.integrity_authority,
    )
    assert terminal.state == "all_rejected"
    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *a, **k: None)
    stages = []
    durable = []
    original_gate = publication._AdmissionBinding.revalidate

    def observed_gate(binding, stage):
        stages.append(stage)
        if terminal_drift and stage == "producer_terminal_replay":
            _lose_record(value, value.record, "missing")
            durable.append((_rows(value), _files(value)))
        return original_gate(binding, stage)

    monkeypatch.setattr(publication._AdmissionBinding, "revalidate", observed_gate)
    rows, files = _rows(value), _files(value)
    if terminal_drift:
        with pytest.raises(publication.RSIPythonPublicationError) as caught:
            _call(value, "run", drafts=value.drafts)
        assert caught.value.code == "rsi_python_publication_evidence_invalid"
        assert (_rows(value), _files(value)) == durable[0]
        assert stages[-1] == "producer_terminal_replay"
    else:
        result = _call(value, "run", drafts=value.drafts)
        assert result.publication_status == "all_rejected"
        assert result.journal == value.journal
        assert result.terminal_journal == terminal
        assert result.evaluations == ()
        assert result.rejected_candidate_ids == (candidate.candidate_id,)
        assert stages[-1] == "rsi_python_publication_return"
        assert (_rows(value), _files(value)) == (rows, files)
    assert "producer_terminal_replay" in stages
    assert stages[0] == "rsi_python_publication_entry"
    assert len(verifications) == 3
    assert value.record.production_admission is False


@pytest.mark.parametrize("window", ["entry", "post-checkpoint"])
def test_sqlite_open_race_never_recreates_missing_database(tmp_path, monkeypatch, window):
    value = _fixture(tmp_path, strategy=window == "post-checkpoint")
    original_connect = sqlite3.connect
    active = window == "entry"
    raced_calls, durable = [], []

    def connect_after_removal(database, *args, **kwargs):
        if active:
            assert database == value.ledger.database.as_uri() + "?mode=ro"
            assert kwargs["uri"] is True
            value.ledger.database.unlink()
            raced_calls.append(database)
            durable.append(_durable_snapshot(value.workspace))
        return original_connect(database, *args, **kwargs)

    def checkpoint(stage):
        nonlocal active
        assert stage == "producer_preparation"
        active = True

    monkeypatch.setattr(sqlite3, "connect", connect_after_removal)
    arguments = {"continuation_guard": checkpoint} if window == "post-checkpoint" else {}
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, "run" if window == "post-checkpoint" else "resume", **arguments)
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert len(raced_calls) == 1
    assert not value.ledger.database.exists()
    assert _durable_snapshot(value.workspace) == durable[0]


@pytest.mark.parametrize("operation", ["run", "resume"])
def test_replacement_empty_sqlite_file_is_not_initialized_or_repaired(tmp_path, monkeypatch, operation):
    value = _fixture(tmp_path)
    replacement = tmp_path / "replacement.sqlite3"
    connection = sqlite3.connect(replacement)
    connection.execute("CREATE TABLE inert_empty_fixture (value TEXT)")
    connection.commit()
    connection.close()
    raw = replacement.read_bytes()
    replacement.replace(value.ledger.database)
    _forbid_lower_calls(monkeypatch)
    before = _files(value)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, operation)
    assert caught.value.code == "rsi_python_publication_evidence_invalid"
    assert value.ledger.database.read_bytes() == raw
    assert _files(value) == before


def test_readonly_ledger_scope_nests_restores_and_keeps_other_thread_writer_usable(tmp_path):
    value = _fixture(tmp_path)
    ledger = value.ledger
    original_checkpoint = ledger.controller_checkpoint(value.binding.run_id)

    def query_only():
        connection = ledger._connect()
        try:
            return connection.execute("PRAGMA query_only").fetchone()[0]
        finally:
            connection.close()

    def writer():
        assert query_only() == 0
        return ledger.create_run("independent-writer", DIGEST, {"fixture": "legal-write"})

    with ledger.read_only_observations():
        assert query_only() == 1
        with pytest.raises(RuntimeError, match="inert-scope-exit"), ledger.read_only_observations():
            assert query_only() == 1
            connection = ledger._connect()
            try:
                with pytest.raises(sqlite3.OperationalError, match="readonly"):
                    connection.execute("DELETE FROM rsi_python_admissions")
            finally:
                connection.close()
            raise RuntimeError("inert-scope-exit")
        assert query_only() == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            written = pool.submit(writer).result(timeout=5)
        assert written.logical_id == "independent-writer"
        assert ledger.get_run("independent-writer") == written
        assert ledger.controller_checkpoint(value.binding.run_id) == original_checkpoint
    assert query_only() == 0
    assert ledger.create_run("after-scope", OTHER, {"fixture": "restored-write"}).logical_id == "after-scope"
    assert ledger.controller_checkpoint(value.binding.run_id) == original_checkpoint
