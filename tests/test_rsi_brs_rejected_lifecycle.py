"""Complete original-owner rejection with real local transaction/storage kernels.

Only candidate execution, evaluation and native-process observations are inert
fixtures. The selected worker, one-shot mailbox/admission exchange, rejection
transaction, terminal episode/result and controller checkpoint are real. No
model, producer program, external evaluator or subprocess is executed.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from threading import Event, get_ident
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_brs_rejection_c1 as rejection_fixture
import test_rsi_brs_rejection_provenance as provenance_fixture
import test_rsi_brs_terminal_recovery as terminal_fixture
import test_rsi_python_brs_publication_recovery as retained_fixture
import test_rsi_python_brs_selected_service as selected_fixture
from test_bundle_population import build_context
from test_rsi_python_admission import _rows

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution import native_trusted_attempt as attempt_module
from lunar_evolution import native_trusted_output as output_module
from lunar_evolution import native_trusted_receipt as receipt_module
from lunar_evolution import rsi_brs_native_process_evidence as process_module
from lunar_evolution.native_trusted_scheduler import (
    NativeTrustedProducerRun,
    _NativeTrustedPythonProducerPreparation,
)
from lunar_evolution.producer_process import parse_producer_execution_receipt
from lunar_evolution.python_producer_admission_handoff import PythonProducerAdmissionHandoffSidecar
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_python_brs_publication_inputs import _request_from_native_preparation
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_terminal_lifecycle import open_brs_terminal_lifecycle

inert_only = rejection_fixture.inert_only
sealed_launch = provenance_fixture.sealed_launch
tmp_path = rejection_fixture.tmp_path


@contextmanager
def _natural_rejected_worker(
    root, patch, *, count=1, native_records=True, callback_unknown=False,
):
    """Build all inert producer inputs before capturing the original live owner."""
    context = build_context(root / "pipeline")
    original_setup, original_plan = owner_fixture._setup, owner_fixture._plan

    def plan(binding, request, memory):
        return replace(original_plan(binding, request, memory),
                       evaluator_kind=context.config.evaluator_kind, plan_sha256=None)

    patch.setattr(owner_fixture, "_plan", plan)
    receipt_reader = FunctionType(retained_fixture._receipt_projection.__code__,
                                  vars(receipt_module), "_receipt_projection")
    terminal_reader = FunctionType(retained_fixture._terminal_projection.__code__,
                                   vars(attempt_module), "_terminal_projection")
    patch.setattr(attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", None, raising=False)
    patch.setattr(receipt_module, "build_native_trusted_execution_receipt", receipt_reader)
    for module in (attempt_module, output_module, receipt_module, process_module):
        patch.setattr(module, "recover_native_trusted_attempt", terminal_reader)

    value = rejection_fixture._native_setup(
        root, patch, count=count, context=context, original_owner_setup=original_setup,
    )
    receipt = parse_producer_execution_receipt(json.loads(
        (value.batch / "execution-receipt.json").read_bytes(),
    ))
    value.preparation = _NativeTrustedPythonProducerPreparation(
        NativeTrustedProducerRun(
            retained_fixture._Trap(), receipt,
            replace(value.prepared_output, drafts=retained_fixture._Trap(), bundles=retained_fixture._Trap()),
        ),
        PythonProducerAdmissionHandoffSidecar(value.handoff, value.pin),
    )
    if native_records:
        terminal_fixture._seed_original_native_records(value)
        registration = json.loads((value.batch / "process-registration.json").read_bytes())
        relative = registration["target_execution_snapshot_relative_path"]
        if relative is not None:
            target = value.batch / relative
            target.parent.mkdir(mode=0o700)
            target.write_bytes((value.native.producer_root / value.native.intent.executable_relative).read_bytes())
            target.chmod(0o500)
    # These files belong to the unselected input fixture. The actual shared
    # transaction below must create its own journal and anchor exactly once.
    for name in ("journal.prepared.json", "python-producer-admission-anchor.json"):
        path = value.batch / name
        path.rename(path.with_name(name + ".rejected-lifecycle-input"))

    messages, release, abort = Queue(), Event(), Event()
    value.callback_calls = []

    def callback(delivery):
        value.callback_calls.append(delivery.to_dict())
        if callback_unknown:
            raise RuntimeError("inert_rejected_callback_unknown")
        assert delivery.publication_status == "all_rejected"
        return SolverResult(
            episode_id=value.request.episode_id, request_sha256=value.request.digest(),
            status="failed", terminal_reason="inert-native-all-rejected",
            candidate_receipt_sha256=None, execution_receipt_sha256=None,
            official_evaluation_receipt_sha256=None, trace_digest=delivery.payload_sha256,
        )

    def operation(request):
        native_plan = owner_fixture._plan(value.binding, request, value.controller.snapshot)
        native_plan = replace(
            native_plan, bootstrap_descriptor_sha256=value.native.artifact.descriptor.digest(),
            bootstrap_artifact_sha256=value.native.artifact.artifact_sha256, plan_sha256=None,
        )
        claim = value.ledger.claim_native_episode(request, plan_sha256=native_plan.plan_sha256)
        messages.put((request, native_plan, get_ident()))
        release.wait()
        if abort.is_set():
            raise owner_fixture._StopWorker()
        result = value.session.worker_endpoint.receive_and_settle(
            value.request_message, callback=callback, check=lambda: None,
        )
        value.ledger.publish_native_episode_result(
            request, plan_sha256=native_plan.plan_sha256, result=result, expected_claim=claim,
        )
        return result

    value.operation = operation
    with selected_fixture._wave(value) as wave:
        handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(value.controller._execute_brs_intent, wave, wave.state,
                             handoff.episode_id, handoff)
        try:
            request, native_plan, worker_thread = messages.get(timeout=20)
            value.request, value.plan, value.worker_thread = request, native_plan, worker_thread
            value.ready, value.future, value.pool, value.wave = release, future, pool, wave
            value.owner = _BRSLineageCheckpointOwner(
                value.controller, wave, request=request, memory=value.controller.snapshot, native_plan=native_plan,
            )
            value.request_message = _request_from_native_preparation(
                value.preparation, handoff, native_plan=native_plan,
                expected_head_sha256=handoff.head_sha256, expected_state_sha256=handoff.state_sha256,
            )
            value.mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker_thread)
            value.session = open_brs_terminal_lifecycle(
                value.owner, value.mailbox, future=future, executor=pool,
            )
            yield value
        finally:
            abort.set()
            release.set()
            if hasattr(value, "session"):
                value.session._exchange.fail()
            if hasattr(value, "mailbox"):
                value.mailbox.close()
            wave.channel.close()
            pool.shutdown(wait=True)


def _assert_single_failed_worker(value):
    execution = value.future.result(timeout=20)
    assert execution.result.status == execution.episode.status == "failed"
    assert [row.state for row in value.ledger.history(value.episode_id)] == ["running", "failed"]
    assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
    assert value.ledger.inspect_native_episode_claim(
        execution.request, plan_sha256=value.plan.plan_sha256,
    ).status == "failed"
    assert len(value.callback_calls) == value.gateway.calls == 1
    assert value.ledger.get_episode(value.sibling_id) is None
    assert not any(thread.is_alive() for thread in value.pool._threads)
    return execution


@pytest.mark.parametrize("count", [1, 2])
def test_genuine_rejection_reaches_natural_worker_terminal_without_mailbox_deadlock(tmp_path, monkeypatch, count):
    with _natural_rejected_worker(tmp_path, monkeypatch, count=count) as value:
        original = deepcopy(value.wave.state)
        value.ready.set()
        result = value.session.serve(value.preparation, check=lambda: None, timeout=30)
        assert result.transaction.publication_status == "all_rejected"
        assert result.transaction.manifest is None
        execution = _assert_single_failed_worker(value)
        assert value.session._exchange.admission_state == "received"
        assert value.owner._rejection_ready_state == "committed"
        assert value.wave.channel._requests[value.episode_id].ack is not None
        assert value.wave.state["budget_state"] == original["budget_state"]
        assert value.wave.state["root_snapshot"] == original["root_snapshot"]
        assert value.wave.state["executions"] == {}
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
        assert execution.verifier.outcome != "pass"


def test_failed_rejection_callback_remains_fenced_and_cannot_be_retried(tmp_path, monkeypatch):
    with _natural_rejected_worker(tmp_path, monkeypatch, callback_unknown=True) as value:
        value.ready.set()
        with pytest.raises((RSILearningError, RuntimeError)):
            value.session.serve(value.preparation, check=lambda: None, timeout=30)
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.episode_result(value.episode_id) is None
        assert len(value.callback_calls) == value.gateway.calls == 1
        before = _rows(value)
        with pytest.raises(RSILearningError):
            value.session.serve(value.preparation, check=lambda: None, timeout=30)
        assert _rows(value) == before
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)


def test_rejected_terminal_root_settlement_writes_one_execution_and_preserves_reservation(tmp_path, monkeypatch):
    with _natural_rejected_worker(tmp_path, monkeypatch) as value:
        original = deepcopy(value.wave.state)
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=30)
        execution = _assert_single_failed_worker(value)
        value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        head, state = value.ledger.controller_checkpoint(value.binding.run_id)
        assert head == value.wave.checkpoint_sha256
        assert set(state["executions"]) == {value.episode_id}
        assert state["executions"][value.episode_id] == value.controller._serialize_execution(execution)
        assert state["budget_state"] == original["budget_state"]
        assert state["root_snapshot"] == original["root_snapshot"]
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == {}
        history, rows = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
        with pytest.raises(RSILearningError):
            value.controller._python_admission_settle_original_brs_terminal(value.owner, value.session)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert _rows(value) == rows
        assert value.gateway.calls == 1


def _fresh_controller(value):
    return RSILearningController(
        value.gateway, ledger=RSILedger(value.ledger.database),
        producer_sidecar=value.sidecar, producer_workspace=value.workspace,
    )


def test_fresh_controller_recovers_terminal_rejection_into_one_root_execution(tmp_path, monkeypatch):
    with _natural_rejected_worker(tmp_path, monkeypatch) as value:
        original = deepcopy(value.wave.state)
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=30)
        execution = _assert_single_failed_worker(value)
        assert value.wave.state["executions"] == {}
    recovered = _fresh_controller(value)
    result = recovered.reconcile_brs_terminal(value.binding.run_id, value.episode_id,
                                              **terminal_fixture._context(value))
    assert result["observation"]["status"] == "ready"
    assert result["consumption"].consumed is True
    _head, state = recovered.ledger.controller_checkpoint(value.binding.run_id)
    assert state["executions"] == {value.episode_id: recovered._serialize_execution(execution)}
    assert state["budget_state"] == original["budget_state"]
    assert state["root_snapshot"] == original["root_snapshot"]
    assert recovered.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == {}
    assert len(value.callback_calls) == value.gateway.calls == 1
    before = _rows(value)
    with pytest.raises(RSILearningError, match="obligation_missing"):
        recovered.reconcile_brs_terminal(value.binding.run_id, value.episode_id,
                                        **terminal_fixture._context(value))
    assert _rows(value) == before


def test_unknown_native_process_never_settles_root_or_restarts_solver(tmp_path, monkeypatch):
    with _natural_rejected_worker(tmp_path, monkeypatch, native_records=False) as value:
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=30)
        _assert_single_failed_worker(value)
    before = _rows(value)
    result = _fresh_controller(value).reconcile_brs_terminal(
        value.binding.run_id, value.episode_id, **terminal_fixture._context(value),
    )
    assert result["observation"]["status"] == "unknown"
    assert result["consumption"] is None
    assert _rows(value) == before
    assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["executions"] == {}
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    assert len(value.callback_calls) == value.gateway.calls == 1


def test_root_race_after_fresh_rejection_observation_preserves_fence(tmp_path, monkeypatch):
    with _natural_rejected_worker(tmp_path, monkeypatch) as value:
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=30)
        _assert_single_failed_worker(value)
    recovered = _fresh_controller(value)
    original_consume = recovered.ledger._consume_brs_reconcile_obligation
    calls = []

    def racing_consume(run_id, episode_id, evidence, *, expected_pins=None, settled_execution=None):
        head, state = recovered.ledger.controller_checkpoint(run_id)
        assert expected_pins["root_checkpoint_sha256"] == head
        assert settled_execution["result"]["status"] == "failed"
        calls.append(head)
        recovered.ledger.write_controller_checkpoint(run_id, state, expected_sha256=head)
        return original_consume(run_id, episode_id, evidence, expected_pins=expected_pins,
                                settled_execution=settled_execution)

    monkeypatch.setattr(recovered.ledger, "_consume_brs_reconcile_obligation", racing_consume)
    obligations = value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    with pytest.raises(RSILearningError, match="^rsi_brs_terminal_consume_drift$"):
        recovered.reconcile_brs_terminal(value.binding.run_id, value.episode_id,
                                        **terminal_fixture._context(value))
    assert len(calls) == 1
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == obligations
    assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["executions"] == {}
    assert len(value.callback_calls) == value.gateway.calls == 1
