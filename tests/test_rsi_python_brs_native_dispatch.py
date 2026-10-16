"""Private BRS dispatch through the actual shared transaction/stage/commit kernel.

The waiting selected worker, retained receipt/output readers, prepared/anchor
creation, lineage CAS, publication and archive readback are real. Evaluation,
artifact projection and all-rejected terminal projection are fixed inert fixture
boundaries installed before original owner/policy capture. They do not establish
real candidate execution, evaluator acceptance or public BRS routing.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Thread, get_ident
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_brs_publication_recovery as retained

from lunar_evolution import bundle_evolution
from lunar_evolution import producer_bundle_receipts as receipts
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_brs_publication_lineage as lineage
from lunar_evolution import rsi_python_brs_native_dispatch as dispatch
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.bundle_evolution import MultiFileCandidatePipeline
from lunar_evolution.candidate_evaluation_spec import CandidateEvaluationSpec
from lunar_evolution.producer_bundle_control import native_producer_bundle_budget_sha256
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("n")


def _forbidden(*_args, **_kwargs):
    pytest.fail("private dispatch fixture invoked external execution")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", _forbidden)
    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", _forbidden)


def _unlocked_callback(*_args):
    assert not staging._HELD_PUBLICATION_LOCKS.get(), "caller hook ran under publication lock"
    return False


def _unlocked_config(self):
    _unlocked_callback()
    return {"fixture": self.fingerprint}


def _unlocked_budget(*_args):
    _unlocked_callback()
    return 600.0


def _inert_evaluate(self, strategy, draft, *, journal_id, ordinal, journal_candidate,
                    admission_plan, journal_sha256):
    from pathlib import Path
    from types import SimpleNamespace

    from lunar_evolution import producer_bundle_staging
    from lunar_evolution.algorithm import EvaluationReport
    from lunar_evolution.candidate_evaluation_spec import canonical_json

    assert not producer_bundle_staging._HELD_PUBLICATION_LOCKS.get()
    root = Path(strategy.context.workspace)
    planned = journal_candidate
    binding = root / "evolution/producer-batches" / journal_id / "native-drafts" / planned.candidate_id / "draft-binding.json"
    binding.parent.mkdir(parents=True)
    value = {"protocol": "lunar-native-draft-binding-v1", "ordinal": ordinal,
             "journal_id": journal_id, "journal_sha256": journal_sha256,
             **{name: getattr(planned, name) for name in ("candidate_id", "bundle_id", "bundle_sha256",
                 "parent_id", "generation", "iteration", "island_id")}}
    with binding.open("xb") as stream:
        stream.write(canonical_json(value))
    binding.chmod(0o600)
    validity = int((root / "fixture-dispatch-validity").read_text())
    report = EvaluationReport("1", "inert-dispatch", validity, float(validity), {},
                              () if validity else ({"code": "inert_rejection",
                                                    "message": "inert fixture rejection"},),
                              quality=float(validity))
    return SimpleNamespace(candidate_id=planned.candidate_id, report=report, draft=draft,
                           planned=planned, binding=binding, journal_id=journal_id,
                           ordinal=ordinal, journal_sha256=journal_sha256)


def _inert_artifact(workspace, result, *, authority, python_handoff_sha256=None):
    import hashlib
    from pathlib import Path

    from lunar_evolution.evolution import Candidate, CandidateReceipt
    from lunar_evolution.producer_bundle_receipts import (
        ProducerBundleEvaluationReceipt,
        ProducerBundleExecutionReceipt,
        _collect_retained_evidence,
    )
    from lunar_evolution.producer_bundle_staging import ProducerBundlePublicationArtifact

    root = Path(workspace)
    planned, draft = result.planned, result.draft
    source = draft.source.encode()
    source_sha = hashlib.sha256(source).hexdigest()
    receipt = CandidateReceipt.from_report(result.report, candidate_id=planned.candidate_id,
        source_sha256=source_sha, contract_sha256=authority.contract_sha256,
        evaluator_kind=authority.evaluator_kind, evaluator_fingerprint=authority.evaluator_fingerprint,
        dependency_sha256=authority.dependency_sha256, environment_sha256=authority.environment_sha256,
        runner_fingerprint=authority.runner_fingerprint, generator_fingerprint=authority.generator_fingerprint,
        parent_id=planned.parent_id,
        generation=planned.generation, iteration=planned.iteration, island_id=planned.island_id)
    integrity = {"schema_version": authority.schema_version, "contract_sha256": authority.contract_sha256, "evaluator_kind": authority.evaluator_kind,
        "evaluator_fingerprint": authority.evaluator_fingerprint, "runner_fingerprint": authority.runner_fingerprint,
        "dependency_sha256": authority.dependency_sha256, "environment_sha256": authority.environment_sha256,
        "generator_fingerprint": authority.generator_fingerprint, "candidate_id": planned.candidate_id,
        "parent_id": planned.parent_id, "generation": planned.generation,
        "iteration": planned.iteration, "island_id": planned.island_id,
        "receipt_sha256": receipt.receipt_sha256, "source_sha256": source_sha}
    record = Candidate(planned.candidate_id, "evolution/candidates/" + planned.candidate_id + "/" + draft.filename,
        planned.parent_id, planned.generation, planned.iteration, "population", planned.island_id,
        result.report, metadata=draft.metadata, created_at=0.0, source_sha256=source_sha,
        receipt_sha256=receipt.receipt_sha256, integrity=integrity)
    evidence = _collect_retained_evidence(root, (result.binding,
        root / "evolution/producer-batches" / result.journal_id / "journal.prepared.json"))
    execution = ProducerBundleExecutionReceipt(planned.candidate_id, planned.bundle_sha256,
        "a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64, "0" * 64)
    evaluation = ProducerBundleEvaluationReceipt(planned.candidate_id, planned.bundle_sha256,
        "a" * 64, "b" * 64, "c" * 64, "1" * 64, {"inert_fixture": True},
        result.report.to_dict(), True, False, python_handoff_sha256=python_handoff_sha256)
    return ProducerBundlePublicationArtifact(planned.candidate_id, {draft.filename: source},
        record.to_dict(), receipt.to_dict(), execution_receipt_sha256=execution.digest(),
        evaluation_receipt_sha256=evaluation.digest(), execution_receipt=execution.to_dict(),
        evaluation_receipt=evaluation.to_dict(), retained_evidence=evidence)


def _inert_rejected(workspace, journal, preflight, evaluations, *, authority, checkpoint):
    from dataclasses import replace
    from pathlib import Path

    from lunar_evolution.candidate_evaluation_spec import canonical_json

    assert len(evaluations) == 1 and evaluations[0].report.validity == 0
    checkpoint("all_rejected")
    terminal = replace(journal, state="all_rejected", publication_phase="committed",
        candidates=tuple(replace(item, status="rejected", execution_receipt_sha256="c" * 64,
            evaluation_receipt_sha256="d" * 64) for item in journal.candidates),
        archive_after_sha256=journal.base_archive_sha256, state_after_sha256=journal.base_state_sha256,
        terminal_marker_sha256="e" * 64, journal_sha256=None)
    path = Path(workspace) / "evolution/producer-batches" / journal.journal_id / "journal.json"
    with path.open("xb") as stream:
        stream.write(canonical_json(terminal.to_dict()))
    path.chmod(0o600)
    return terminal


@contextmanager
def _waiting(tmp_path, monkeypatch, *, validity=1, control="original"):
    evaluate = FunctionType(_inert_evaluate.__code__, vars(bundle_evolution), _inert_evaluate.__name__)
    artifact = FunctionType(_inert_artifact.__code__, vars(receipts), _inert_artifact.__name__)
    rejected = FunctionType(_inert_rejected.__code__, vars(transaction), _inert_rejected.__name__)
    original = retained._setup

    def setup(root, patch):
        value = original(root, patch)
        patch.setattr(MultiFileCandidatePipeline, "evaluate_draft_non_publishing", evaluate)
        patch.setattr(receipts, "build_native_producer_bundle_publication_artifact", artifact)
        patch.setattr(transaction, "build_native_producer_bundle_publication_artifact", artifact)
        patch.setattr(transaction, "finalize_producer_bundle_all_rejected", rejected)
        original_context = value.strategy.context
        harness = root / "fixture-inert-harness"
        harness.write_bytes(b"# never invoked\n")
        evaluator = CandidateEvaluationSpec(hashlib.sha256(harness.read_bytes()).hexdigest(),
            harness.stat().st_size, (str(Path(sys.executable).resolve()), "-I"), timeout_seconds=3)
        pipeline = MultiFileCandidatePipeline(evaluator=evaluator, harness_path=harness,
            input_root=root, inputs=(), command=(str(Path(sys.executable).resolve()),),
            dependency_sha256=value.native.dependency_sha256,
            environment_sha256=value.native.environment_sha256, timeout_seconds=3)
        # The inherited inert context already has original binding authority.
        # Install only operational fixture hooks before owner/policy capture;
        # no pipeline configuration or evaluator authority is claimed here.
        for name, item in (("bundle_pipeline", pipeline), ("cancelled", _unlocked_callback),
                           ("remaining_timeout", _unlocked_budget), ("continuation_guard", _unlocked_callback)):
            object.__setattr__(original_context, name, item)
        strategy = value.strategy
        execution_control = (None if control == "missing" else SolveExecutionControl(600,
            cancellation_callbacks=(_unlocked_callback,), **({"clock": lambda: 1.0} if control == "custom" else {})))
        value.native = replace(value.native, strategy=strategy, execution_control=execution_control,
                               cancelled=_unlocked_callback)
        configuration = value.gateway.producer_config
        value.gateway.producer_config = replace(configuration,
            inputs=type(configuration.inputs)(value.native, value.sidecar, value.proof))
        value.strategy, value.control = strategy, execution_control
        (value.workspace / "fixture-dispatch-validity").write_text(str(validity))
        value.journal = replace(value.journal,
            budget_sha256=native_producer_bundle_budget_sha256(strategy, execution_control), journal_sha256=None)
        # These earlier reader fixtures were installed without a transaction.
        # Preserve them separately before owner capture; the real shared kernel
        # must create its own prepared journal and anchor in this dispatch.
        for name in ("journal.prepared.json", "python-producer-admission-anchor.json"):
            path = value.batch / name
            path.rename(path.with_name(name + ".dispatch-setup-original"))
        return value

    monkeypatch.setattr(retained, "_setup", setup)
    with retained._waiting(tmp_path, monkeypatch) as value:
        assert value.owner._phase == "new"
        assert value.plan.task_id == value.request.episode_id
        assert not (value.batch / "journal.prepared.json").exists()
        assert not (value.batch / "python-producer-admission-anchor.json").exists()
        yield value


def _call(value):
    return dispatch._run_original_brs_native_publication(value.owner, value.request_message,
        original_preparation=value.preparation)


def _unchanged(value, before):
    owner_fixture._unchanged(value, before)
    assert not (value.batch / "journal.prepared.json").exists()
    assert not (value.batch / "python-producer-admission-anchor.json").exists()
    assert not (value.workspace / "evolution/producer-publication.json").exists()
    assert not (value.batch / "stage").exists()


def test_private_original_dispatch_uses_shared_success_kernel_and_distinct_owner_heads(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        run_id = value.binding.run_id
        history_before = value.ledger.controller_checkpoint_history(run_id)
        budget, snapshot = deepcopy(value.wave.state["budget_state"]), deepcopy(value.wave.state["root_snapshot"])
        writes, original_write = [], value.ledger.write_controller_checkpoint

        def write(run_id, state, *, expected_sha256):
            assert get_ident() == value.owner_thread != value.worker_thread
            assert value.ledger.controller_lock_held(run_id)
            assert not staging._HELD_PUBLICATION_LOCKS.get()
            writes.append((expected_sha256, deepcopy(state)))
            return original_write(run_id, state, expected_sha256=expected_sha256)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", write)
        result = _call(value)
        assert result.publication_status == "published" and len(result.admitted_candidate_ids) == 1
        assert result.published_journal.state == "published" and value.owner._phase == "terminal"
        assert not value.owner._poisoned
        history = value.ledger.controller_checkpoint_history(run_id)[len(history_before):]
        assert len(history) == 5 and len({head for head, _state in history}) == 5
        entries = [state["producer_publication_lineage"]["batches"][0] for _head, state in history]
        assert [entry["state"] for entry in entries] == ["before", "before", "before", "staged", "terminal"]
        assert not history[0][1].get("python_admission_refs", {})
        assert history[1][1]["python_admission_refs"] == history[2][1]["python_admission_refs"]
        assert not entries[1]["evidence_pins"]
        assert set(entries[2]["evidence_pins"]) == {"journal.prepared.json"}
        assert len(writes) == 4  # Original reference pin has its own SQLite transaction.
        assert value.ledger.controller_checkpoint(run_id) == (value.owner._head, value.wave.state)
        assert value.wave.state["budget_state"] == budget and value.wave.state["root_snapshot"] == snapshot
        assert (value.batch / "journal.prepared.json").is_file()
        assert (value.batch / "python-producer-admission-anchor.json").is_file()
        assert (value.batch / "journal.prepared.json.dispatch-setup-original").is_file()
        assert not (value.workspace / "evolution/producer-publication.json").exists()
        assert (value.workspace / "evolution/candidates" / result.admitted_candidate_ids[0] / "main.py").read_bytes() == b"# inert candidate\n"
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert not value.ready.is_set() and value.messages.empty()
        assert not value.wave.channel._requests and not value.wave.channel._queue
        policy = json.loads(value.owner._policy_bytes)
        assert policy["online_publication"] is False and policy["production_admission"] is False
        assert value.controller.producer_multi_episode_publication is False


@pytest.mark.parametrize("control", ["missing", "custom"])
def test_missing_or_custom_clock_control_refuses_before_owner_observation_or_effect(tmp_path, monkeypatch, control):
    with _waiting(tmp_path, monkeypatch, control=control) as value:
        before = owner_fixture._capture(value)
        monkeypatch.setattr(lineage._BRSLineageCheckpointOwner, "_success_observe", _forbidden)
        monkeypatch.setattr(lineage._BRSLineageCheckpointOwner, "_before_unlocked", _forbidden)
        with pytest.raises(RSILearningError, match="monotonic_control_required"):
            _call(value)
        _unchanged(value, before)


def test_public_native_transaction_still_refuses_brs_owner_before_evaluation(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        with pytest.raises(transaction.NativeProducerBundleTransactionError):
            transaction.run_native_producer_bundle_publication_transaction(value.workspace,
                value.strategy, value.prepared_output.drafts, value.admission,
                journal_id=value.plan.journal_id, producer_multi_episode_publication=True,
                lineage_owner=value.owner)
        _unchanged(value, before)


def test_all_rejected_native_terminal_is_retained_then_brs_refuses_without_publication(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch, validity=0) as value:
        with pytest.raises(RSILearningError, match="all_rejected_unsupported"):
            _call(value)
        terminal = json.loads((value.batch / "journal.json").read_bytes())
        assert terminal["state"] == "all_rejected"
        assert value.owner._phase == "prepared-evidence" and value.owner._poisoned
        assert not (value.batch / "stage").exists()
        assert not (value.workspace / "evolution/producer-publication.json").exists()
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.episode_result(value.episode_id) is None


def test_original_numeric_revalidator_returns_immediately_before_first_unknown_marker(tmp_path, monkeypatch):
    events = []
    control_source = str(Path(transaction.__file__).with_name("producer_bundle_control.py"))
    staging_source = str(Path(staging.__file__))

    def profile(frame, event, _arg):
        if event == "return" and frame.f_code.co_filename == control_source and frame.f_code.co_name == "revalidate_after_observation":
            events.append("numeric")
        if event == "call" and frame.f_code.co_name in {
            "_unlocked_callback", "_unlocked_budget", "_unlocked_config", "_success_observe", "_before_control_live", "rsi_fingerprint_config",
        }:
            events.append("caller-observation")
        if event == "call" and frame.f_code.co_filename == staging_source and frame.f_code.co_name == "_replace_existing":
            content = frame.f_locals.get("content", b"")
            if b'"status":"unknown"' in content or b'"status": "unknown"' in content:
                events.append("unknown")

    with _waiting(tmp_path, monkeypatch) as value:
        previous = sys.getprofile()
        try:
            sys.setprofile(profile)
            _call(value)
        finally:
            sys.setprofile(previous)
        assert "unknown" in events
        first = events.index("unknown")
        assert first > 0 and events[first - 1] == "numeric"
        assert value.control._clock is time.monotonic


@pytest.mark.parametrize("foreign", [False, True])
def test_outer_publication_lock_refuses_before_source_hooks_even_for_foreign_workspace(tmp_path, monkeypatch, foreign):
    with _waiting(tmp_path, monkeypatch) as value:
        workspace = value.workspace
        if foreign:
            workspace = tmp_path / "foreign"
            workspace.mkdir()
            (workspace / "evolution").mkdir()
        before = owner_fixture._capture(value)
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", _forbidden)
        with staging._locked(workspace), pytest.raises(RSILearningError, match="before_unlocked_owner_required"):
            _call(value)
        _unchanged(value, before)
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["foreign-owner", "phase", "request", "preparation", "foreign-thread"])
def test_private_dispatch_rejects_foreign_or_reused_authority_without_prepared_effect(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        if fault == "phase":
            value.owner.checkpoint_before(owner_fixture._before(value))
        before = owner_fixture._capture(value)
        if fault == "foreign-thread":
            errors = []
            def run():
                try:
                    _call(value)
                except RSILearningError as exc:
                    errors.append(exc)
            thread = Thread(target=run)
            thread.start()
            thread.join(15)
            assert not thread.is_alive() and len(errors) == 1
        else:
            with pytest.raises(RSILearningError):
                dispatch._run_original_brs_native_publication(object() if fault == "foreign-owner" else value.owner,
                    object() if fault == "request" else value.request_message,
                    original_preparation=object() if fault == "preparation" else value.preparation)
        _unchanged(value, before)


@pytest.mark.parametrize("stage", ["producer_staging_locked", "producer_commit_locked"])
def test_late_same_bytes_receipt_inode_replacement_refuses_before_unknown_marker(tmp_path, monkeypatch, stage):
    with _waiting(tmp_path, monkeypatch) as value:
        path = value.batch / "execution-receipt.json"
        original_bytes, original_inode = path.read_bytes(), path.stat().st_ino
        replaced = []
        transaction_source = str(Path(transaction.__file__))
        def profile(frame, event, _arg):
            if (not replaced and event == "call" and frame.f_code.co_filename == transaction_source
                    and frame.f_code.co_name == "checkpoint_with_handoff" and frame.f_locals.get("stage") == stage):
                replacement = path.with_name("execution-receipt.same-bytes-replacement")
                replacement.write_bytes(original_bytes)
                replacement.chmod(0o600)
                replacement.replace(path)
                replaced.append(path.stat().st_ino)
        previous = sys.getprofile()
        try:
            sys.setprofile(profile)
            with pytest.raises((RSILearningError, transaction.NativeProducerBundleTransactionError)):
                _call(value)
        finally:
            sys.setprofile(previous)
        assert len(replaced) == 1 and replaced[0] != original_inode
        assert path.read_bytes() == original_bytes and value.owner._poisoned
        marker = value.workspace / "evolution/producer-publication.json"
        assert not marker.exists() or json.loads(marker.read_bytes())["status"] == "staged"
        assert not (value.batch / "journal.published.json").exists()
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.episode_result(value.episode_id) is None
