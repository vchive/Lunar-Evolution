"""Local inert late handoff sequencing without launching any producer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_native_trusted_scheduler import _attempt, _call_context, _context

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)


def _stages(monkeypatch, events, *, receipt_link="d" * 64):
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(
        execution_receipt_sha256=receipt_link, drafts=(),
        admission_plan=SimpleNamespace(digest=lambda: "b" * 64),
    )

    def stage(name, result):
        def call(*_args, **_kwargs):
            events.append(name)
            return result
        return call

    for attribute, name, result in (
        ("run_native_trusted_attempt", "attempt", _attempt()),
        ("persist_native_trusted_execution_receipt", "receipt", receipt),
        ("prepare_native_trusted_output", "output", output),
    ):
        monkeypatch.setattr(scheduler, attribute, stage(name, result))
    return receipt, output


def _handoff(context, **changes):
    fields = {
        "run_id": context.intent.run_id, "journal_id": context.intent.journal_id,
        "parent_task_id": context.intent.parent_task_id, "task_id": context.intent.task_id,
        "binding_sha256": "a" * 64, "sidecar_raw_sha256": "a" * 64,
        "sidecar_pin_sha256": "a" * 64,
        "launch_intent_sha256": context.intent.digest(),
        "attestation_sha256": context.attestation.digest(),
        "runtime_manifest_sha256": "a" * 64, "runtime_tree_sha256": "a" * 64,
        "executable_owner_sha256": "a" * 64, "native_execution_receipt_sha256": "d" * 64,
        "terminal_sha256": "a" * 64, "runtime_observation_sha256": "a" * 64,
        "broker_transcript_sha256": "a" * 64, "envelope_sha256": "a" * 64,
        "materials_sha256": "a" * 64, "contract_sha256": context.contract.digest(),
        "evaluator_sha256": "e" * 64, "runner_sha256": "f" * 64,
        "dependency_sha256": "1" * 64, "environment_sha256": "2" * 64,
        "admission_plan_sha256": "b" * 64, "request_budget": 1,
        "wall_timeout_seconds": 5, "deadline_unix": 4102444800.125,
        **changes,
    }
    batch = context.workspace / "evolution/producer-batches" / context.intent.journal_id
    batch.mkdir(parents=True, mode=0o700, exist_ok=True)
    return persist_python_producer_admission_handoff_pinned(
        batch, handoff=build_python_producer_admission_handoff(**fields),
    )


def _options(supplier, *, observer=None, revalidator=None):
    return {
        "strategy": object(), "python_handoff_after_execution": supplier,
        "prepared_observer": observer or (lambda _journal: None),
        "evidence_revalidator": revalidator or (lambda _stage: None),
    }


def test_join_supplies_original_pin_only_after_receipt_and_output(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    receipt, output = _stages(monkeypatch, events)
    original = None

    def supplier(observed_receipt, observed_output):
        nonlocal original
        assert observed_receipt is receipt and observed_output is output
        assert events == ["attempt", "receipt", "output"]
        events.append("supplier")
        original = _handoff(context)
        return original

    def observer(_journal):
        events.append("prepared")

    def revalidate(_stage):
        events.append("revalidate")

    def publication(*_args, **kwargs):
        events.append("publication")
        assert kwargs["python_handoff_sha256"] == original.handoff.handoff_sha256
        assert kwargs["python_handoff_file_pin"] == original.file_pin
        assert kwargs["native_execution_receipt_sha256"] == receipt.receipt_sha256
        kwargs["prepared_observer"](object())
        kwargs["evidence_revalidator"]("fixture-before-evaluation")
        events.append("evaluation")
        return SimpleNamespace(publication_status="published")

    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", publication)
    result = _call_context(context, **_options(supplier, observer=observer, revalidator=revalidate))
    assert events == ["attempt", "receipt", "output", "supplier", "publication",
                      "prepared", "revalidate", "evaluation"]
    assert result.status == "published"


@pytest.mark.parametrize("missing", ["supplier", "observer", "revalidator", "strategy"])
def test_incomplete_join_refuses_before_attempt(tmp_path, monkeypatch, missing):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events)
    options = _options(lambda *_args: pytest.fail("incomplete join called supplier"))
    field = {"supplier": "python_handoff_after_execution", "observer": "prepared_observer",
             "revalidator": "evidence_revalidator", "strategy": "strategy"}[missing]
    options[field] = None
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_join_invalid"):
        _call_context(context, **options)
    assert events == []


def test_unbound_publication_preserves_ordinary_transaction_arguments(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events)

    def publication(*_args, **kwargs):
        assert not {"python_handoff_sha256", "python_handoff_file_pin", "prepared_observer",
                    "evidence_revalidator"}.intersection(kwargs)
        events.append("publication")
        return SimpleNamespace(publication_status="published")

    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", publication)
    assert _call_context(context, strategy=object()).status == "published"
    assert events == ["attempt", "receipt", "output", "publication"]


def test_receipt_output_drift_never_calls_supplier(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events, receipt_link="9" * 64)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="receipt_binding_mismatch"):
        _call_context(context, **_options(lambda *_args: pytest.fail("receipt drift called supplier")))
    assert events == ["attempt", "receipt", "output"]


@pytest.mark.parametrize("field", ["receipt", "output_receipt", "admission_plan"])
def test_supplier_cannot_replace_original_execution_evidence(tmp_path, monkeypatch, field):
    context, events = _context(tmp_path), []
    receipt, output = _stages(monkeypatch, events)

    def supplier(*_args):
        retained = _handoff(context)
        if field == "receipt":
            receipt.receipt_sha256 = "9" * 64
        elif field == "output_receipt":
            output.execution_receipt_sha256 = "9" * 64
        else:
            output.admission_plan = SimpleNamespace(digest=lambda: "9" * 64)
        return retained

    monkeypatch.setattr(
        scheduler, "run_native_producer_bundle_publication_transaction",
        lambda *_args, **_kwargs: pytest.fail("supplier evidence rewrite reached publication"),
    )
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call_context(context, **_options(supplier))


@pytest.mark.parametrize("field", [
    "native_execution_receipt_sha256", "admission_plan_sha256", "launch_intent_sha256",
    "attestation_sha256", "contract_sha256", "evaluator_sha256", "runner_sha256",
    "dependency_sha256", "environment_sha256",
])
def test_original_handoff_binding_drift_never_reaches_publication(tmp_path, monkeypatch, field):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events)
    monkeypatch.setattr(
        scheduler, "run_native_producer_bundle_publication_transaction",
        lambda *_args, **_kwargs: pytest.fail("handoff drift reached publication"),
    )
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call_context(context, **_options(lambda *_args: _handoff(context, **{field: "9" * 64})))
    assert events == ["attempt", "receipt", "output"]


@pytest.mark.parametrize("reason", ["exception", "untyped", "touched", "replaced"])
def test_supplier_failure_and_original_file_pin_loss_preserve_refusal(tmp_path, monkeypatch, reason):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events)

    def supplier(*_args):
        if reason == "exception":
            raise ValueError("inert supplier failure")
        if reason == "untyped":
            return object()
        retained = _handoff(context)
        path = context.workspace / "evolution/producer-batches" / context.intent.journal_id / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
        if reason == "touched":
            import os
            os.utime(path, ns=(retained.file_pin.mtime_ns + 1, retained.file_pin.mtime_ns + 1))
        else:
            original_bytes = path.read_bytes()
            path.rename(path.with_suffix(".original"))
            path.write_bytes(original_bytes)
            path.chmod(0o600)
        return retained

    monkeypatch.setattr(
        scheduler, "run_native_producer_bundle_publication_transaction",
        lambda *_args, **_kwargs: pytest.fail("invalid supplier reached publication"),
    )
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call_context(context, **_options(supplier))


@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_supplier_stop_prevents_handoff_read_or_publication(tmp_path, monkeypatch, reason):
    context, events = _context(tmp_path), []
    _stages(monkeypatch, events)
    ticks = [100.0]
    control = SolveExecutionControl(10, clock=lambda: ticks[0])

    def supplier(*_args):
        retained = _handoff(context)
        if reason == "cancelled":
            control.cancel()
        else:
            ticks[0] = control.deadline
        return retained

    monkeypatch.setattr(
        scheduler, "read_python_producer_admission_handoff_pinned",
        lambda *_args, **_kwargs: pytest.fail("supplier stop read handoff"),
    )
    expected = SolveExecutionCancelled if reason == "cancelled" else SolveExecutionBudgetExceeded
    with pytest.raises(expected):
        _call_context(context, execution_control=control, **_options(supplier))
