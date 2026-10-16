"""Real local prepared transaction/owner joins with an inert native attempt seam."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_rsi_native_scheduler_prepared_boundary import _provider
from test_rsi_python_admission import _files, _rows
from test_rsi_python_admission_flow import _lose_record
from test_rsi_python_admission_owner import (
    _EvaluationBoundary,
    _owner,
    _state,
    _unregistered_publication,
    no_actual_worker_or_evaluator,  # noqa: F401 -- imported autouse fixture
)
from test_rsi_python_brs_publication import _drive

from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_native_scheduler as scheduler
from lunar_evolution.python_producer_admission_handoff import (
    read_python_producer_admission_handoff_pinned,
)
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_admission_bridge import (
    PythonAdmissionBridgeAdapter,
    PythonAdmissionBridgeError,
    build_python_admission_bridge_descriptor,
)


def _joined_provider(value, monkeypatch, events):
    original_plan = value.plan
    provider = _provider(value)
    # Reuse this fixture's original claimed plan; the selector is inert and never runs.
    value.plan = original_plan
    monkeypatch.setattr(scheduler, "component_fingerprint", lambda _value: original_plan.candidate_selector_sha256)

    def handoff_after_execution(receipt, output):
        events.append("handoff")
        assert receipt.receipt_sha256 == value.handoff.native_execution_receipt_sha256
        assert output.admission_plan == value.admission_plan
        return read_python_producer_admission_handoff_pinned(
            value.batch / "python-producer-admission-handoff.json", expected_file_pin=value.pin,
        )

    provider.context.producer_root = value.workspace
    provider.context.strategy = value.strategy
    provider.context.groups = ()
    provider.context.broker_config = SimpleNamespace()
    provider.context.execution_control = None
    provider.context.cancelled = None
    provider.context.failure_ledger = None
    provider.context.python_handoff_after_execution = handoff_after_execution
    return provider


@pytest.mark.parametrize("lose_after_pin", [False, True])
def test_opted_in_scheduler_pins_real_owner_before_evaluation_and_retains_loss(
    tmp_path, monkeypatch, lose_after_pin,
):
    value = _unregistered_publication(tmp_path)
    events, records, evaluations, checkpoints = [], [], [], []
    provider = _joined_provider(value, monkeypatch, events)
    original_request = value.ledger.history(value.binding.run_id)[0]

    def inert_native_attempt(workspace, **kwargs):
        # This substitutes only the native process stages. The actual publication,
        # handoff pin and original DRS controller CAS remain real.
        events.append("native-output")
        assert not _rows(value)["rsi_python_admissions"]
        receipt = SimpleNamespace(receipt_sha256=value.handoff.native_execution_receipt_sha256)
        output = SimpleNamespace(admission_plan=value.admission_plan, drafts=value.drafts)
        sidecar = kwargs["python_handoff_after_execution"](receipt, output)

        def prepared(journal):
            events.append("prepared")
            assert (value.batch / "journal.prepared.json").is_file()
            assert not records
            kwargs["prepared_observer"](journal)
            reference = _state(value)["python_admission_refs"][value.episode_id]
            record = value.ledger.python_admission_record(
                value.binding.run_id, value.episode_id, journal.journal_id,
                expected_record_sha256=reference["record_sha256"],
            )
            records.append(record)
            checkpoints.append(_state(value))
            events.append("pinned")
            if lose_after_pin:
                _lose_record(value, record, "missing")

        return transaction.run_native_producer_bundle_publication_transaction(
            workspace, kwargs["strategy"], value.drafts, value.admission_plan,
            journal_id=value.journal.journal_id, run_id=value.journal.run_id,
            parent_task_id=value.journal.parent_task_id, task_id=value.journal.task_id,
            native_execution_receipt_sha256=receipt.receipt_sha256,
            python_handoff_sha256=sidecar.handoff.handoff_sha256,
            python_handoff_file_pin=sidecar.file_pin,
            prepared_observer=prepared, evidence_revalidator=kwargs["evidence_revalidator"],
        )

    def inert_evaluation(*_args, **_kwargs):
        assert events == ["native-output", "handoff", "prepared", "pinned"]
        assert len(records) == 1
        assert _state(value)["python_admission_refs"][value.episode_id]["record_sha256"] == records[0].record_sha256
        evaluations.append("evaluated")
        raise _EvaluationBoundary()

    monkeypatch.setattr(scheduler, "run_native_trusted_producer", inert_native_attempt)
    monkeypatch.setattr(transaction, "_verify_native_execution_receipt_link", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(value.strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", inert_evaluation)
    expected = RSILearningError if lose_after_pin else _EvaluationBoundary
    with pytest.raises(expected), _owner(value):
        provider(value.request, value.plan)

    assert events == ["native-output", "handoff", "prepared", "pinned"]
    assert evaluations == ([] if lose_after_pin else ["evaluated"])
    assert len(records) == 1 and records[0].production_admission is False
    assert value.ledger.history(value.binding.run_id)[0] == original_request
    assert checkpoints[0]["python_admission_refs"][value.episode_id]["record_sha256"] == records[0].record_sha256
    if lose_after_pin:
        with pytest.raises(RSILearningError, match="rsi_python_admission_record_missing"):
            _state(value)
    else:
        assert _state(value) == checkpoints[0]
    assert (value.batch / "journal.prepared.json").is_file()
    assert len(_rows(value)["rsi_python_admissions"]) == (0 if lose_after_pin else 1)


@pytest.mark.parametrize("entry", ["dispatch", "join"])
@pytest.mark.parametrize("supplier", ["configured", "disabled", "callback-context"])
def test_brs_scheduler_refuses_worker_publication_before_inputs_or_callbacks(
    tmp_path, monkeypatch, entry, supplier,
):
    value = _unregistered_publication(tmp_path)
    events = []
    provider = _joined_provider(value, monkeypatch, events)
    if supplier == "disabled":
        provider.context.python_handoff_after_execution = None
    elif supplier == "callback-context":
        class CallbackContext:
            def __getattribute__(self, name):
                pytest.fail("BRS worker read scheduler context before publication refusal")

        provider.context = CallbackContext()

    def forbidden(*_args, **_kwargs):
        pytest.fail("BRS worker reached native/input/ready/evaluator/publication boundary")

    monkeypatch.setattr(provider, "_inputs", forbidden)
    monkeypatch.setattr(scheduler, "run_native_trusted_producer", forbidden)
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", forbidden)
    monkeypatch.setattr(transaction, "run_native_producer_bundle_publication_transaction", forbidden)
    monkeypatch.setattr(value.controller, "_request_python_admission_for_brs_worker", forbidden)
    monkeypatch.setattr(value.strategy.context.bundle_pipeline, "evaluate_draft_non_publishing", forbidden)
    observations = []

    def operation():
        before = _rows(value), _files(value)
        try:
            if entry == "dispatch":
                provider(value.request, value.plan)
            else:
                provider._python_publication_join(value.request, value.plan, object())
        finally:
            observations.append((_rows(value), _files(value)) == before)

    with pytest.raises(
        scheduler.NativeRSISchedulerProviderError,
        match="^rsi_native_scheduler_brs_owner_publication_required$",
    ):
        _drive(value, monkeypatch, operation)
    assert observations == [True]
    assert events == []
    assert not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize("argument", ["request", "plan"])
def test_brs_scheduler_refuses_before_worker_input_class_callbacks(tmp_path, monkeypatch, argument):
    value = _unregistered_publication(tmp_path)
    events, callbacks = [], []
    provider = _joined_provider(value, monkeypatch, events)

    class CallbackInput:
        def __getattribute__(self, name):
            callbacks.append(name)
            pytest.fail("BRS scheduler read worker input before publication refusal")

    request = CallbackInput() if argument == "request" else value.request
    plan = CallbackInput() if argument == "plan" else value.plan
    with pytest.raises(
        scheduler.NativeRSISchedulerProviderError,
        match="^rsi_native_scheduler_brs_owner_publication_required$",
    ):
        _drive(value, monkeypatch, lambda: provider(request, plan))
    assert callbacks == events == []
    assert not _rows(value)["rsi_python_admissions"]


@pytest.mark.parametrize("field", ["episode_id", "native_plan_sha256", "prepared_journal_sha256"])
def test_drs_bridge_refuses_a_valid_record_from_other_prepared_evidence(tmp_path, field):
    value = _unregistered_publication(tmp_path)
    changed = replace(
        value.record, **{field: "foreign-episode" if field == "episode_id" else "e" * 64},
        record_sha256=None,
    )
    changed = replace(changed, record_sha256=changed.digest())
    descriptor = build_python_admission_bridge_descriptor(
        run_id=value.plan.run_id, episode_id=value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
    )
    hook = SimpleNamespace(_pin_python_admission_for_active_flow=lambda *_args, **_kwargs: changed)
    with pytest.raises(PythonAdmissionBridgeError, match="drs_record_invalid"):
        PythonAdmissionBridgeAdapter(hook, descriptor).pin_drs(descriptor)


def test_drs_bridge_refuses_callback_record_content_before_serialization(tmp_path):
    value = _unregistered_publication(tmp_path)
    seen = []

    class CallbackDict(dict):
        def items(self):
            seen.append("items")
            pytest.fail("record shape invoked callback")

    object.__setattr__(value.record, "admission_anchor", CallbackDict(value.record.admission_anchor))
    descriptor = build_python_admission_bridge_descriptor(
        run_id=value.plan.run_id, episode_id=value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
    )
    hook = SimpleNamespace(_pin_python_admission_for_active_flow=lambda *_args, **_kwargs: value.record)
    with pytest.raises(PythonAdmissionBridgeError):
        PythonAdmissionBridgeAdapter(hook, descriptor).pin_drs(descriptor)
    assert seen == []
