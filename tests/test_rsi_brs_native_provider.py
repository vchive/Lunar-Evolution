"""Component wiring with real claims/exchange and explicit inert native doubles.

Controller/source-policy and completion readers are doubled here. These tests
prove fixed private provider routing, never ordinary full-chain acceptance.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_rsi_python_brs_publication_inputs as inputs_fixture
from test_native_trusted_scheduler import _context
from test_rsi_brs_preparation_exchange import _endpoint
from test_rsi_native_provenance import payload
from test_rsi_native_rejection import rejection_evidence

import lunar_evolution.rsi_brs_native_provider as native
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.rsi_brs_native_completion import (
    _BRSNativeCompletionPin,
    _BRSPublishedNativeCompletion,
)
from lunar_evolution.rsi_brs_preparation_exchange import _BRSNativePreparationExchange
from lunar_evolution.rsi_brs_serial_driver import (
    _BRSReservedChildScope,
    _BRSReservedSerialObservation,
)
from lunar_evolution.rsi_controller import RSILearningController, _PythonAdmissionBRSWave
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from lunar_evolution.rsi_native_gateway import NativeRSIExecutionConfig, NativeRSIReceiptBundle
from lunar_evolution.rsi_native_inputs import NativeRSIInputDescriptor
from lunar_evolution.rsi_native_provenance import read_native_rsi_provenance
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
)
from lunar_evolution.rsi_producer_gateway import PythonProducerRSISolverGateway
from lunar_evolution.rsi_python_brs_terminal_lifecycle import _BRSWorkerTerminalEndpoint
from lunar_evolution.rsi_store import RSILedger

prepared = inputs_fixture.prepared


@pytest.fixture
def binding_fixture(prepared, tmp_path, monkeypatch):
    value = prepared
    memory = EMPTY_MEMORY_SNAPSHOT
    request = replace(value.plan.request, memory_snapshot_sha256=memory.digest())
    plan = replace(value.plan, request=request, request_sha256=request.digest(),
                   memory_snapshot_sha256=memory.digest(), plan_sha256=None)
    handoff = replace(value.handoff, request_sha256=request.digest(), root_snapshot_sha256=memory.digest())
    ledger = RSILedger(tmp_path / "provider.sqlite3")
    local = tmp_path / "native"
    local.mkdir()
    source = _context(local)
    context = NativeRSISchedulerContext(value.workspace, local / "producer", source.intent,
        source.attestation, source.artifact, source.broker, source.contract,
        (BundleGroup("candidate", "main.py", ("main.py",)),), "local", "e" * 64, "f" * 64,
        "1" * 64, "2" * 64, object(), failure_ledger=ledger,
        python_handoff_after_execution=lambda *_a: value.preparation.handoff)
    provider = NativeRSISchedulerProvider(context)
    gateway = object.__new__(PythonProducerRSISolverGateway)
    gateway.config = NativeRSIExecutionConfig(ledger, lambda *_a: plan, provider)
    controller = object.__new__(RSILearningController)
    controller.ledger = ledger
    controller.producer_known_rejection = True
    controller.producer_multi_episode_publication = True
    controller.producer_child_execution = True
    state = {"mode": "brs", "plan": {"mode": "brs", "reserved_native_serial": True, "max_workers": 1},
        "producer_child_execution": True, "producer_multi_episode_publication": True,
        "producer_brs_checkpoint_policy": {"mode": "brs", "max_workers": 1,
                                          "production_admission": False, "online_publication": False}}
    wave = _PythonAdmissionBRSWave(controller, state, plan.run_id, (request.episode_id,), ledger,
        value.workspace, object(), threading.get_ident(), "a" * 64, b"original", object(), {})
    deadline = time.monotonic() + 30
    exchange = _BRSNativePreparationExchange(request, expected_plan_sha256=plan.plan_sha256, deadline=deadline)
    scope = _BRSReservedChildScope(_BRSReservedSerialObservation(None, None, (), None), None,
                                  request, memory, gateway, plan, exchange, deadline, threading.get_ident())
    wave.reserved_scope, wave.selected_handoff = scope, handoff
    provider.bind_python_admission_controller(controller)
    inputs = NativeRSIInputDescriptor(value.workspace, plan.journal_id, value.workspace / "inputs",
        request.digest(), memory.digest(), "c" * 64, canonical_json(request.to_dict()),
        memory.to_bytes(), b"{}", None, "d" * 64)
    events = []

    def inert_gate(_self, *_a, **_kw):
        events.append(("controller_gate", threading.get_ident()))

    for method in ("_python_admission_active_brs_owner", "_python_admission_active_brs_worker",
                   "_python_admission_assert_selected_brs", "_python_admission_bridge_wait_check"):
        monkeypatch.setattr(RSILearningController, method, inert_gate)
    monkeypatch.setattr(NativeRSISchedulerProvider, "validate_preclaim", lambda *_a, **_kw: None)
    monkeypatch.setattr(NativeRSISchedulerProvider, "_inputs", lambda *_a, **_kw: inputs)
    monkeypatch.setattr(NativeRSISchedulerProvider, "rsi_fingerprint_config", lambda *_a: {"original": True})
    monkeypatch.setattr(native, "_assert_plan_binding", lambda *_a: None)

    def prepare(*_a, **options):
        assert threading.get_ident() != scope.owner_thread
        assert options["parent_deadline"] == deadline
        assert options["python_handoff_after_execution"] is context.python_handoff_after_execution
        assert options["execution_control"] is context.execution_control
        assert options["cancelled"] is context.cancelled
        options["evidence_revalidator"]("inert_preparation")
        events.append(("prepare", threading.get_ident()))
        return value.preparation

    monkeypatch.setattr(native, "_prepare_native_trusted_python_producer", prepare)
    value = SimpleNamespace(**vars(value), request=request, native_plan=plan, selected=handoff,
        ledger=ledger, provider=provider, scope=scope, wave=wave, controller=controller,
        inputs=inputs, events=events, monkeypatch=monkeypatch)
    return value


def _bind(value):
    return native.bind_brs_native_provider(value.provider, controller=value.controller, wave=value.wave,
                                          scope=value.scope, handoff=value.selected)


def _claim(value):
    return value.ledger.claim_native_episode(value.request, plan_sha256=value.native_plan.plan_sha256)


def _run_with_original_exchange(value, operation=None, *, reserved=True):
    with ThreadPoolExecutor(max_workers=1) as pool:
        entered = threading.Event()

        def worker():
            entered.set()
            return value.provider(value.request, value.native_plan) if operation is None else operation()

        future = pool.submit(worker)
        assert entered.wait(2)
        value.scope.exchange.attach_worker(future, pool)
        offer = value.scope.exchange.take(check=lambda: None)
        original = _endpoint(SimpleNamespace(handoff=value.selected, plan=value.native_plan), offer)
        endpoint = _BRSWorkerTerminalEndpoint(
            original._mailbox, original._exchange, original._handoff_bytes, original._plan_sha256,
            offer.thread.ident, id(offer.thread), _reserved_success=reserved,
        )
        value.scope.exchange.return_endpoint(offer, endpoint)
        return future.result(timeout=3)


def _inert_endpoint(value, *, after_callback=None):
    def receive(endpoint, message, *, callback, check):
        _BRSWorkerTerminalEndpoint._identity(endpoint)
        check()
        assert message.episode_id == value.request.episode_id
        result = callback(object())  # Caller delivery is deliberately not an outcome.
        if after_callback is not None:
            after_callback()
        endpoint._status = "settled"
        return result

    value.monkeypatch.setattr(_BRSWorkerTerminalEndpoint, "receive_and_settle", receive)


def _published_components(value):
    wire = payload()
    bundle = NativeRSIReceiptBundle(*(kind.from_dict(wire["bundle"][name]) for kind, name in (
        (NativeCandidateRecord, "candidate"), (NativeExecutionReceipt, "execution"),
        (NativeEvaluationReceipt, "evaluation"), (NativePublicationReceipt, "publication"))))
    pin = _BRSNativeCompletionPin(b"original-inert-completion-pin")
    observed = _BRSPublishedNativeCompletion(bundle, canonical_json(wire), pin)
    value.monkeypatch.setattr(native, "_observe", lambda *_a: (None, None, None, None,
                                                               SimpleNamespace(state="published")))
    value.monkeypatch.setattr(native, "read_brs_live_published_completion", lambda *_a: observed)
    calls = []

    def repeated(provider, request, plan, *, expected_pin, expected_provenance_sha256):
        assert expected_pin is pin
        saved = read_native_rsi_provenance(provider.provenance_batch)
        assert saved["provenance_sha256"] == expected_provenance_sha256
        calls.append(expected_provenance_sha256)
        return replace(bundle, provenance_sha256=expected_provenance_sha256)

    value.monkeypatch.setattr(native, "read_brs_live_published_provenance", repeated)
    value.provider.provenance_batch.mkdir(parents=True, exist_ok=True)
    return calls


def test_private_fixed_success_uses_only_preparation_seam_original_exchange_and_writer_digest(binding_fixture):
    value = binding_fixture
    calls = _published_components(value)
    _inert_endpoint(value)
    bound = _bind(value)
    claim = _claim(value)
    result = _run_with_original_exchange(value)
    assert type(result) is NativeRSIReceiptBundle
    assert calls == [result.provenance_sha256] * 2
    assert bound._state == "returned" and bound._claim == claim
    assert value.scope.exchange._state == "consumed"
    assert [event[0] for event in value.events].count("prepare") == 1


def test_private_fixed_preparation_forwards_explicit_native_observation_supplier(binding_fixture, monkeypatch):
    value = binding_fixture
    context = value.provider.context

    def supplier(_run):
        raise AssertionError("this component test stops at the native preparation seam")

    object.__setattr__(context, "python_handoff_after_execution", None)
    object.__setattr__(context, "python_handoff_after_native_execution", supplier)
    object.__setattr__(context, "live_modules_sink", object())
    monkeypatch.setattr(NativeRSISchedulerContext, "_assert_live_modules_sink", lambda self: self.live_modules_sink)
    calls = []

    def prepare(*_args, **options):
        assert options["python_handoff_after_execution"] is None
        assert options["python_handoff_after_native_execution"] is supplier
        assert options["live_modules_sink"] is context.live_modules_sink
        options["evidence_revalidator"]("inert_preparation")
        calls.append(options)
        return value.preparation

    monkeypatch.setattr(native, "_prepare_native_trusted_python_producer", prepare)
    _published_components(value)
    _inert_endpoint(value)
    _bind(value)
    _claim(value)
    assert type(_run_with_original_exchange(value)) is NativeRSIReceiptBundle
    assert len(calls) == 1
    assert value.provider._live_rejection is None
    assert value.ledger.inspect_native_episode_claim(value.request,
        plan_sha256=value.native_plan.plan_sha256).status == "started"
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_private_fixed_rejection_has_separate_original_second_reader(binding_fixture):
    value = binding_fixture
    evidence, pin, reads = rejection_evidence(count=1), _BRSNativeCompletionPin(b"rejection"), []
    value.monkeypatch.setattr(native, "_observe", lambda *_a: (None, None, None, None,
        SimpleNamespace(state="all_rejected")))

    def read(*_a, expected_pin=None):
        assert expected_pin is None or expected_pin is pin
        reads.append(expected_pin)
        return evidence, pin

    value.monkeypatch.setattr(native, "read_brs_live_rejection_completion", read)
    _inert_endpoint(value)
    bound = _bind(value)
    _claim(value)

    def operation():
        returned = value.provider(value.request, value.native_plan)
        assert NativeRSISchedulerProvider.recover_live_rejection(
            value.provider, value.request, value.native_plan) is evidence
        return returned

    assert _run_with_original_exchange(value, operation) is evidence
    assert reads == [None, pin, pin]
    assert bound._state == "returned" and value.provider._live_rejection is None


@pytest.mark.parametrize("fault", ["request_copy", "plan_drift", "no_claim", "deadline", "cancelled",
                                    "config", "foreign_scope", "foreign_controller"])
def test_worker_validation_failure_poisons_original_exchange_before_preparation(binding_fixture, fault):
    value = binding_fixture
    bound = _bind(value)
    if fault != "no_claim":
        _claim(value)
    request, plan = value.request, value.native_plan
    if fault == "request_copy":
        request = replace(request)
    elif fault == "plan_drift":
        plan = replace(plan, task_id="foreign", plan_sha256=None)
    elif fault == "deadline":
        value.monkeypatch.setattr(native.time, "monotonic", lambda: value.scope.deadline + 1)
    elif fault == "cancelled":
        object.__setattr__(value.provider.context, "cancelled", lambda: True)
    elif fault == "config":
        value.monkeypatch.setattr(NativeRSISchedulerProvider, "rsi_fingerprint_config", lambda *_a: {"new": True})
    elif fault == "foreign_scope":
        value.wave.reserved_scope = replace(value.scope)
    elif fault == "foreign_controller":
        value.provider._python_admission_controller = object()
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RSILearningError):
        pool.submit(value.provider, request, plan).result(timeout=3)
    assert bound._state == "unknown" and value.scope.exchange._failed
    assert not any(event[0] == "prepare" for event in value.events)
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_before_claim_read_is_worker_only_and_never_creates_claim(binding_fixture):
    value = binding_fixture
    bound = _bind(value)
    with pytest.raises(RSILearningError, match="original_worker_required"):
        native.assert_brs_native_provider_binding(value.provider, value.request,
                                                  value.native_plan, before_claim=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(native.assert_brs_native_provider_binding, value.provider,
            value.request, value.native_plan, before_claim=True).result(timeout=3) is bound
        assert value.ledger.inspect_native_episode_claim(value.request,
            plan_sha256=value.native_plan.plan_sha256) is None
        _claim(value)
        with pytest.raises(RSILearningError, match="fresh_claim_required"):
            pool.submit(native.assert_brs_native_provider_binding, value.provider,
                value.request, value.native_plan, before_claim=True).result(timeout=3)


def test_preparation_exception_wakes_original_owner_without_borrowing_owner_fail(binding_fixture):
    value = binding_fixture
    bound = _bind(value)
    claim = _claim(value)

    def unknown(*_a, **_kw):
        raise RuntimeError("inert_preparation_unknown")

    value.monkeypatch.setattr(native, "_prepare_native_trusted_python_producer", unknown)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="inert_preparation_unknown"):
            pool.submit(value.provider, value.request, value.native_plan).result(timeout=3)
        with pytest.raises(RSILearningError, match="unavailable"):
            value.scope.exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError):
            pool.submit(value.provider, value.request, value.native_plan).result(timeout=3)
    assert bound._state == "unknown"
    assert value.ledger.inspect_native_episode_claim(value.request,
        plan_sha256=value.native_plan.plan_sha256) == claim


@pytest.mark.parametrize("stage", ["entry", "preparation"])
def test_replaced_child_cannot_intercept_original_failure_cleanup(binding_fixture, stage):
    value = binding_fixture
    bound = _bind(value)
    _claim(value)

    class Hook:
        def __getattribute__(self, _name):
            pytest.fail("foreign child used during original worker cleanup")

    if stage == "entry":
        bound._child = Hook()
        expected = RSILearningError
    else:
        def unknown(*_args, **_kwargs):
            bound._child = bound._original = Hook()
            raise RuntimeError("original preparation unknown")

        value.monkeypatch.setattr(native, "_prepare_native_trusted_python_producer", unknown)
        expected = RuntimeError
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(expected):
        pool.submit(value.provider, value.request, value.native_plan).result(timeout=3)
    assert bound._state == "unknown" and value.scope.exchange._failed is True
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_reserved_provider_refuses_legacy_endpoint_without_success_ack_requirement(binding_fixture):
    value = binding_fixture
    bound = _bind(value)
    claim = _claim(value)
    with pytest.raises(RSILearningError, match="original_endpoint_required"):
        _run_with_original_exchange(value, reserved=False)
    assert bound._state == "unknown" and value.scope.exchange._failed is True
    assert value.ledger.inspect_native_episode_claim(value.request,
        plan_sha256=value.native_plan.plan_sha256) == claim
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_callback_unknown_retains_started_claim_and_never_persists_success(binding_fixture):
    value = binding_fixture
    bound = _bind(value)
    _claim(value)
    value.monkeypatch.setattr(native, "_observe", lambda *_a: (None, None, None, None,
                                                              SimpleNamespace(state="evaluating")))
    _inert_endpoint(value)
    with pytest.raises(RSILearningError, match="known_terminal_required"):
        _run_with_original_exchange(value)
    assert bound._state == "unknown" and value.scope.exchange._failed
    assert not (value.provider.provenance_batch / "native-rsi.provenance.json").exists()
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_duplicate_original_dispatch_never_repeats_preparation_or_publication(binding_fixture):
    value = binding_fixture
    _published_components(value)
    _inert_endpoint(value)
    bound = _bind(value)
    _claim(value)

    def operation():
        result = value.provider(value.request, value.native_plan)
        with pytest.raises(RSILearningError, match="duplicate_dispatch"):
            value.provider(value.request, value.native_plan)
        return result

    _run_with_original_exchange(value, operation)
    assert [event[0] for event in value.events].count("prepare") == 1
    assert bound._state == "unknown"


@pytest.mark.parametrize("fault", ["bound", "foreign_scope", "foreign_handoff", "foreign_thread", "claim"])
def test_owner_binding_refuses_invalid_scope_before_native_effect(binding_fixture, fault):
    value = binding_fixture
    kwargs = {"controller": value.controller, "wave": value.wave,
              "scope": value.scope, "handoff": value.selected}
    if fault == "bound":
        _bind(value)
    elif fault == "foreign_scope":
        kwargs["scope"] = replace(value.scope)
    elif fault == "foreign_handoff":
        kwargs["handoff"] = replace(value.selected)
    elif fault == "claim":
        _claim(value)
    with pytest.raises(RSILearningError):
        if fault == "foreign_thread":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(native.bind_brs_native_provider, value.provider, **kwargs).result(timeout=3)
        else:
            native.bind_brs_native_provider(value.provider, **kwargs)
    assert not any(event[0] == "prepare" for event in value.events)


def test_unbound_public_entry_retains_original_refusal_and_invalid_binding_never_falls_back(binding_fixture):
    value = binding_fixture
    assert native.assert_brs_native_provider_binding(value.provider, object(), object()) is None

    def refused(_self):
        raise RSILearningError("original_public_brs_refusal")

    value.monkeypatch.setattr(NativeRSISchedulerProvider, "_refuse_brs_worker_publication", refused)
    with pytest.raises(RSILearningError, match="original_public_brs_refusal"):
        value.provider(value.request, value.native_plan)
    value.provider._brs_native_binding = object()
    with pytest.raises(RSILearningError, match="rsi_brs_native_provider_binding_invalid"):
        value.provider(value.request, value.native_plan)


def test_second_read_rejects_drs_owner_and_wrong_worker(binding_fixture):
    value = binding_fixture
    bound = _bind(value)
    _claim(value)
    bound._state, bound._completion, bound._pin = "returned", rejection_evidence(count=1), _BRSNativeCompletionPin(b"p")
    bound._worker = threading.Thread()
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RSILearningError, match="original_worker_required"):
        pool.submit(value.provider.recover_live_rejection, value.request, value.native_plan).result(timeout=3)
    assert value.provider._live_rejection is None


def test_invalid_request_shape_is_refused_without_calling_serializer_hook(binding_fixture):
    value = binding_fixture
    calls = []
    object.__setattr__(value.request, "to_dict", lambda: calls.append("hook"))
    with pytest.raises(RSILearningError):
        _bind(value)
    assert calls == [] and not any(event[0] == "prepare" for event in value.events)
