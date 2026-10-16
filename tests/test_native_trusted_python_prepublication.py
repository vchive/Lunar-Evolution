"""Inert producer-only stop boundary; no process, evaluation or transaction."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from test_native_trusted_scheduler import _attempt, _context
from test_native_trusted_scheduler_python_join import _handoff as _write_handoff
from test_producer_bundle_admission import _plan
from test_producer_bundle_population import _verified_bundle
from test_producer_bundle_transaction import _formal_execution_receipt

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.native_trusted_output import NativeTrustedOutputPreparation
from lunar_evolution.producer_bundle_population import prepare_producer_bundle_drafts
from lunar_evolution.producer_handoff import ProducerResultEnvelope
from lunar_evolution.producer_process import parse_producer_execution_receipt
from lunar_evolution.python_producer_admission_handoff import PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME


def _stages(context, monkeypatch, events):
    receipt = parse_producer_execution_receipt(_formal_execution_receipt(
        journal_id=context.intent.journal_id, run_id=context.intent.run_id,
        parent_task_id=context.intent.parent_task_id, task_id=context.intent.task_id,
    ))
    bundle = _verified_bundle(context.workspace)
    drafts = prepare_producer_bundle_drafts(context.workspace, (bundle,))
    plan = _plan(drafts)
    envelope = ProducerResultEnvelope(
        schema_version="1", producer_id="producer", producer_fingerprint="b" * 64,
        status="completed", contract_sha256=context.contract.digest(), budget={"attempts": 1},
        materials=(),
    )
    output = NativeTrustedOutputPreparation(
        process_terminal_sha256="a" * 64, output_capture_sha256="b" * 64,
        envelope_bytes_sha256="c" * 64, envelope=envelope, bundles=(bundle,), drafts=drafts,
        admission_plan=plan, execution_receipt_sha256=receipt.receipt_sha256,
        request_coverage="brokered_requests_only", publication_eligible=True,
    )
    context.preparation_receipt, context.preparation_output = receipt, output

    def stage(name, result):
        def call(*_args, **_kwargs):
            events.append(name)
            return result
        return call

    for attr, name, result in (
        ("run_native_trusted_attempt", "attempt", _attempt()),
        ("persist_native_trusted_execution_receipt", "receipt", receipt),
        ("prepare_native_trusted_output", "output", output),
    ):
        monkeypatch.setattr(scheduler, attr, stage(name, result))
    return receipt, output


def _handoff(context, **changes):
    return _write_handoff(context, **{
        "native_execution_receipt_sha256": context.preparation_receipt.receipt_sha256,
        "admission_plan_sha256": context.preparation_output.admission_plan.digest(), **changes,
    })

def _inputs(context):
    return {
        "producer_root": context.workspace, "intent": context.intent, "attestation": context.attestation,
        "artifact": context.artifact, "broker_config": context.broker, "contract": context.contract,
        "groups": (), "evaluator_kind": "local", "evaluator_fingerprint": "e" * 64,
        "runner_fingerprint": "f" * 64, "dependency_sha256": "1" * 64, "environment_sha256": "2" * 64,
    }


def _prepare(context, **options):
    options.setdefault("python_handoff_after_execution", lambda *_args: _handoff(context))
    options.setdefault("evidence_revalidator", lambda _stage: None)
    return scheduler._prepare_native_trusted_python_producer(
        context.workspace, **_inputs(context), **options,
    )


def _no_publication(monkeypatch):
    monkeypatch.setattr(
        scheduler, "run_native_producer_bundle_publication_transaction",
        lambda *_args, **_kwargs: pytest.fail("preparation reached publication/evaluation"),
    )


def test_private_preparation_returns_original_evidence_before_publication(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    receipt, output = _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    original = []

    def supplier(observed_receipt, observed_output):
        assert observed_receipt is receipt and observed_output is output
        events.append("handoff")
        original.append(_handoff(context))
        return original[0]

    result = _prepare(context, python_handoff_after_execution=supplier,
                      evidence_revalidator=events.append)
    assert events == ["native_producer_prepublication_entry", "attempt", "receipt", "output",
                      "handoff", "native_producer_prepublication_return"]
    assert type(result) is scheduler._NativeTrustedPythonProducerPreparation
    assert result.run.status == "prepared" and result.run.publication is None
    assert result.run.receipt is receipt and result.run.output is output
    assert result.run.deadline_scope == "native_attempt_only"
    assert result.handoff == original[0] and result.handoff is not original[0]
    assert result.handoff.file_pin is not original[0].file_pin
    assert "_prepare_native_trusted_python_producer" not in scheduler.__all__


@pytest.mark.parametrize("field", ["python_handoff_after_execution", "evidence_revalidator"])
def test_missing_hook_refuses_before_attempt_or_other_hook(tmp_path, monkeypatch, field):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    options = {"python_handoff_after_execution": lambda *_: pytest.fail("supplier ran"),
               "evidence_revalidator": lambda *_: pytest.fail("hook ran"), field: None}
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_prepublication_invalid"):
        _prepare(context, **options)
    assert events == []


@pytest.mark.parametrize("options", [
    {"strategy": object()}, {"prepared_observer": lambda _: None},
    {"known_failure": True}, {"producer_multi_episode_publication": True},
    {"lineage_owner": object()}, {"_python_prepublication": 1},
])
def test_private_core_rejects_publication_or_failure_mix_before_effects(tmp_path, monkeypatch, options):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    settings = {
        "_python_prepublication": True,
        "python_handoff_after_execution": lambda *_: pytest.fail("supplier ran"),
        "evidence_revalidator": lambda *_: pytest.fail("hook ran"),
    }
    settings.update(options)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_prepublication_invalid"):
        scheduler._run_native_trusted_producer(context.workspace, **_inputs(context), **settings)
    assert events == []


@pytest.mark.parametrize("field", [
    "native_execution_receipt_sha256", "admission_plan_sha256", "launch_intent_sha256",
    "attestation_sha256", "contract_sha256", "evaluator_sha256", "runner_sha256",
    "dependency_sha256", "environment_sha256",
])
def test_original_handoff_bindings_still_refuse(tmp_path, monkeypatch, field):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _prepare(context, python_handoff_after_execution=lambda *_: _handoff(
            context, **{field: "9" * 64},
        ))


@pytest.mark.parametrize("mutation", ["receipt", "output_receipt", "admission", "touched", "replaced"])
def test_return_hook_cannot_refresh_original_evidence(tmp_path, monkeypatch, mutation):
    context, events = _context(tmp_path), []
    receipt, output = _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    original = []

    def supplier(*_args):
        original.append(_handoff(context))
        return original[0]

    def revalidate(stage):
        if stage != "native_producer_prepublication_return":
            return
        if mutation == "receipt":
            object.__setattr__(receipt, "receipt_sha256", "9" * 64)
        elif mutation == "output_receipt":
            object.__setattr__(output, "execution_receipt_sha256", "9" * 64)
        elif mutation == "admission":
            object.__setattr__(output, "admission_plan", SimpleNamespace(digest=lambda: "9" * 64))
        else:
            path = (context.workspace / "evolution/producer-batches" / context.intent.journal_id
                    / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME)
            if mutation == "touched":
                ns = original[0].file_pin.file_mtime_ns + 1
                os.utime(path, ns=(ns, ns))
            else:
                raw = path.read_bytes()
                path.rename(path.with_suffix(".original"))
                path.write_bytes(raw)
                path.chmod(0o600)

    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _prepare(context, python_handoff_after_execution=supplier, evidence_revalidator=revalidate)
    # The interrupted attempt is not retried; existing evidence is retained.
    assert events == ["attempt", "receipt", "output"]
    assert (context.workspace / "evolution/producer-batches" / context.intent.journal_id
            / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME).is_file()


@pytest.mark.parametrize("stage", ["entry", "return"])
@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_hook_stop_preserves_original_lifecycle_without_another_stage(
    tmp_path, monkeypatch, stage, reason,
):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    ticks = [100.0]
    control = SolveExecutionControl(10, clock=lambda: ticks[0])
    reads = []
    reader = scheduler.read_python_producer_admission_handoff_pinned

    def read(*args, **kwargs):
        reads.append("read")
        return reader(*args, **kwargs)

    monkeypatch.setattr(scheduler, "read_python_producer_admission_handoff_pinned", read)

    def revalidate(observed_stage):
        if observed_stage == "native_producer_prepublication_" + stage:
            if reason == "cancelled":
                control.cancel()
            else:
                ticks[0] = control.deadline

    expected = SolveExecutionCancelled if reason == "cancelled" else SolveExecutionBudgetExceeded
    with pytest.raises(expected):
        _prepare(context, execution_control=control, evidence_revalidator=revalidate)
    assert events == ([] if stage == "entry" else ["attempt", "receipt", "output"])
    assert reads == ([] if stage == "entry" else ["read"])
    assert control.started_at == 100 and control.deadline == 110


def test_caller_control_scope_survives_successful_preparation(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    control = SolveExecutionControl(10, clock=lambda: 100.0)
    result = _prepare(context, execution_control=control)
    assert result.run.deadline_scope == "caller_lifecycle"
    assert control.started_at == 100 and control.deadline == 110


@pytest.mark.parametrize("hook", ["supplier", "return"])
@pytest.mark.parametrize("field", ["owner", "trusted", "source", "metadata", "envelope"])
def test_nested_payload_mutation_with_unchanged_cached_digests_refuses(
    tmp_path, monkeypatch, hook, field,
):
    context, events = _context(tmp_path), []
    receipt, output = _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    original_receipt_sha = receipt.receipt_sha256
    original_plan_sha = output.admission_plan.digest()

    def mutate():
        if field == "owner":
            receipt.owner_identity["start_time"] += 1
        elif field == "trusted":
            receipt.trusted_execution["broker_journal_identity"]["wall_deadline_ns"] += 1
        elif field == "source":
            output.drafts[0].draft.source_files["pkg/helper.py"] = "VALUE = 2\n"
        elif field == "metadata":
            output.drafts[0].draft.metadata["producer_bundle"]["producer_id"] = "changed"
        else:
            output.envelope.budget["attempts"] += 1

    def supplier(*_args):
        original = _handoff(context)
        if hook == "supplier":
            mutate()
        return original

    def revalidate(stage):
        if hook == "return" and stage == "native_producer_prepublication_return":
            mutate()

    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _prepare(context, python_handoff_after_execution=supplier, evidence_revalidator=revalidate)
    assert receipt.receipt_sha256 == original_receipt_sha
    assert output.admission_plan.digest() == original_plan_sha
    assert events == ["attempt", "receipt", "output"]


@pytest.mark.parametrize("hook", ["entry", "return"])
@pytest.mark.parametrize("composed", [False, True])
@pytest.mark.parametrize("field", ["started_at", "deadline", "timeout_seconds", "clock", "observer", "callbacks"])
def test_hooks_cannot_refresh_parent_or_composed_control(tmp_path, monkeypatch, hook, composed, field):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    control = SolveExecutionControl(10, clock=lambda: 100.0)

    def revalidate(stage):
        if stage != "native_producer_prepublication_" + hook:
            return
        if field in {"started_at", "deadline", "timeout_seconds"}:
            setattr(control, field, getattr(control, field) + 100)
        elif field == "clock":
            control._clock = lambda: 1.0
        elif field == "observer":
            control._observe_stage = lambda _stage: None
        else:
            control.add_cancellation_callback(lambda: False)

    options = {"parent_deadline": 105.0} if composed else {}
    with pytest.raises(scheduler.NativeTrustedSchedulerError) as caught:
        _prepare(context, execution_control=control, evidence_revalidator=revalidate, **options)
    error = caught.value if hook == "entry" else caught.value.__cause__
    assert error.code == "native_trusted_scheduler_python_prepublication_control_changed"
    assert events == ([] if hook == "entry" else ["attempt", "receipt", "output"])


@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_stop_during_last_pinned_read_cannot_return_success(tmp_path, monkeypatch, reason):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)
    ticks = [100.0]
    control = SolveExecutionControl(10, clock=lambda: ticks[0])
    reader = scheduler.read_python_producer_admission_handoff_pinned
    reads = []

    def read(*args, **kwargs):
        result = reader(*args, **kwargs)
        reads.append(result)
        if len(reads) == 2:
            if reason == "cancelled":
                control.cancel()
            else:
                ticks[0] = control.deadline
        return result

    monkeypatch.setattr(scheduler, "read_python_producer_admission_handoff_pinned", read)
    error = SolveExecutionCancelled if reason == "cancelled" else SolveExecutionBudgetExceeded
    with pytest.raises(error):
        _prepare(context, execution_control=control)
    assert len(reads) == 2 and events == ["attempt", "receipt", "output"]


def test_stage_observer_cannot_extend_budget_at_final_checkpoint(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)

    def observe(stage):
        if stage == "native_producer_prepublication_final":
            control.deadline += 100

    control = SolveExecutionControl(10, clock=lambda: 100.0, observe_stage=observe)
    with pytest.raises(scheduler.NativeTrustedSchedulerError) as caught:
        _prepare(context, execution_control=control)
    assert caught.value.__cause__.code == "native_trusted_scheduler_python_prepublication_control_changed"


@pytest.mark.parametrize("mutation", ["touched", "replaced"])
def test_final_observer_cannot_invalidate_original_file_pin(tmp_path, monkeypatch, mutation):
    context, events = _context(tmp_path), []
    _stages(context, monkeypatch, events)
    _no_publication(monkeypatch)

    def observe(stage):
        if stage != "native_producer_prepublication_final":
            return
        path = (context.workspace / "evolution/producer-batches" / context.intent.journal_id
                / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME)
        if mutation == "touched":
            ns = path.stat().st_mtime_ns + 1
            os.utime(path, ns=(ns, ns))
        else:
            raw = path.read_bytes()
            path.rename(path.with_suffix(".original"))
            path.write_bytes(raw)
            path.chmod(0o600)

    control = SolveExecutionControl(10, clock=lambda: 100.0, observe_stage=observe)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _prepare(context, execution_control=control)
