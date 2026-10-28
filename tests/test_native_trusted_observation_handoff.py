"""Original-call passthrough with synthetic sink/strict DTOs, never a runtime acceptance."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_python_prepublication import _handoff, _inputs, _stages
from test_native_trusted_scheduler import _attempt, _context
from test_static_python_fixed_profile import _raw
from test_static_python_fixed_runtime_observation import _runtime_vector

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.producer_request_transport import (
    HostRequestJournalIdentity,
    HostRequestSnapshot,
)


def _fixture(tmp_path, monkeypatch):
    context, events = _context(tmp_path), []
    sink, payload = _runtime_vector()
    context.intent = replace(context.intent, executable_sha256=hashlib.sha256(sink.image).hexdigest(),
                             intent_sha256=None)
    context.attestation = build_producer_launch_attestation(context.intent, "native-observation-fixture")
    receipt, output = _stages(context, monkeypatch, events)
    observed = sink.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                            target_pid=123, manifest_sha256=payload["manifest_sha256"])
    intent = context.intent
    broker = ProducerBrokerObservation(
        HostRequestSnapshot((), 0, 0, 1, 1), context.workspace / "broker-journal.jsonl",
        HostRequestJournalIdentity(intent.launch_id, intent.journal_id, intent.run_id,
                                   intent.parent_task_id, intent.task_id, intent.digest(), 1, 1),
        "8" * 64, 0, True, "completed", (19, 77),
    )
    attempt = replace(_attempt(), live_modules_observation=observed, broker_observation=broker)

    def run(*_args, **_kwargs):
        events.append("attempt")
        return attempt

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", run)
    publication_calls = []

    def publish(*_args, **kwargs):
        publication_calls.append(kwargs)
        return SimpleNamespace(publication_status="published")

    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", publish)
    return SimpleNamespace(context=context, events=events, sink=sink, attempt=attempt,
                           receipt=receipt, output=output, publication_calls=publication_calls)


def _call(value, supplier, *, wrapper="success", **options):
    arguments = {**_inputs(value.context), "python_handoff_after_native_execution": supplier,
                 "live_modules_sink": value.sink, "evidence_revalidator": lambda _stage: None, **options}
    if wrapper == "private":
        return scheduler._prepare_native_trusted_python_producer(value.context.workspace, **arguments)
    arguments.update(strategy=object(), prepared_observer=lambda _journal: None)
    function = (scheduler.run_native_trusted_producer if wrapper == "success"
                else scheduler.run_native_trusted_producer_outcome)
    return function(value.context.workspace, **arguments)


@pytest.mark.parametrize("wrapper", ["success", "outcome", "private"])
def test_new_supplier_receives_exact_current_call_objects_after_preparation(tmp_path, monkeypatch, wrapper):
    value = _fixture(tmp_path, monkeypatch)
    received = []

    def supplier(run):
        assert type(run) is scheduler.NativeTrustedProducerRun
        assert run.attempt is value.attempt
        assert run.receipt is value.receipt and run.output is value.output
        assert run.attempt.live_modules_observation is value.attempt.live_modules_observation
        assert value.events[-3:] == ["attempt", "receipt", "output"]
        assert run.publication is None and run.status == "prepared"
        received.append(run)
        return _handoff(value.context)

    result = _call(value, supplier, wrapper=wrapper)
    assert len(received) == 1
    run = result.run if wrapper == "private" else result
    assert run.attempt is value.attempt and run.receipt is value.receipt and run.output is value.output
    if wrapper == "private":
        assert run is received[0]
    assert len(value.publication_calls) == (0 if wrapper == "private" else 1)
    assert value.attempt.live_modules_observation.production_admission is False


@pytest.mark.parametrize("wrapper", ["success", "outcome", "private"])
def test_both_supplier_forms_refuse_before_attempt(tmp_path, monkeypatch, wrapper):
    value = _fixture(tmp_path, monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="supplier_conflict"):
        _call(value, lambda _run: pytest.fail("new supplier ran"), wrapper=wrapper,
              python_handoff_after_execution=lambda *_args: pytest.fail("old supplier ran"))
    assert value.events == [] and value.publication_calls == []


@pytest.mark.parametrize("wrapper", ["success", "outcome", "private"])
def test_missing_sink_refuses_before_attempt(tmp_path, monkeypatch, wrapper):
    value = _fixture(tmp_path, monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="native_sink_required"):
        _call(value, lambda _run: pytest.fail("missing sink reached supplier"),
              wrapper=wrapper, live_modules_sink=None)
    assert value.events == [] and value.publication_calls == []


def test_missing_original_observation_never_calls_supplier(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    object.__setattr__(value.attempt, "live_modules_observation", None)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call(value, lambda _run: pytest.fail("missing observation reached supplier"))
    assert value.publication_calls == []


@pytest.mark.parametrize("fault", [
    "raw", "same_raw", "digest", "installation", "device", "inode", "pid", "manifest",
    "observation", "attempt", "receipt", "output", "receipt_nested", "output_nested", "sink_source",
    "publication", "status", "deadline_scope",
    "broker_path",
])
def test_supplier_cannot_rewrite_original_objects_or_evidence(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)

    def supplier(run):
        retained = _handoff(value.context)
        observed = run.attempt.live_modules_observation
        mutations = {"raw": ("canonical_bytes", b"changed\n"),
                     "same_raw": ("canonical_bytes", bytes(bytearray(observed.canonical_bytes))),
                     "digest": ("observation_sha256", "9" * 64),
                     "installation": ("installation_sha256", "9" * 64),
                     "device": ("image_device", observed.image_device + 1),
                     "inode": ("image_inode", observed.image_inode + 1),
                     "pid": ("target_pid", observed.target_pid + 1),
                     "manifest": ("manifest_sha256", "9" * 64)}
        if fault in mutations:
            object.__setattr__(observed, *mutations[fault])
        elif fault == "observation":
            object.__setattr__(run.attempt, "live_modules_observation", replace(observed))
        elif fault in {"attempt", "receipt", "output"}:
            object.__setattr__(run, fault, replace(getattr(run, fault)))
        elif fault == "receipt_nested":
            run.receipt.owner_identity["changed"] = True
        elif fault == "output_nested":
            run.output.envelope.budget["attempts"] = 2
        elif fault in {"publication", "status", "deadline_scope"}:
            object.__setattr__(run, fault, {"publication": object(), "status": "published",
                                           "deadline_scope": "caller_lifecycle"}[fault])
        elif fault == "broker_path":
            object.__setattr__(run.attempt.broker_observation, "journal_path",
                               value.context.workspace / "changed-journal.jsonl")
        else:
            object.__setattr__(value.sink, "runtime_main_source",
                               bytes(bytearray(value.sink.runtime_main_source)))
        return retained

    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call(value, supplier)
    assert value.publication_calls == []


def test_final_handoff_read_cannot_replace_original_raw_observation(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    original_read = scheduler.read_python_producer_admission_handoff_pinned

    def read(*args, **kwargs):
        retained = original_read(*args, **kwargs)
        object.__setattr__(value.attempt.live_modules_observation, "canonical_bytes", b"changed\n")
        return retained

    monkeypatch.setattr(scheduler, "read_python_producer_admission_handoff_pinned", read)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _call(value, lambda _run: _handoff(value.context))
    assert value.publication_calls == []
