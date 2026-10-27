"""Original sink routing with inert bytes; no runtime or admission acceptance.

The original sink validator is real. Scheduler effects and publication readers
are doubled explicitly: these tests prove selection, pinning and routing only.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_fixed_live_sink import _request_vector
from test_native_trusted_scheduler import _attempt, _context
from test_rsi_brs_native_provider import (
    _bind,
    _claim,
    _inert_endpoint,
    _published_components,
    _run_with_original_exchange,
)
from test_rsi_brs_native_provider import (
    binding_fixture as binding_fixture,  # noqa: PLC0414 - pytest fixture re-export
)
from test_rsi_python_brs_publication_inputs import prepared as prepared  # noqa: PLC0414
from test_rsi_python_scheduler_inputs import _setup

from lunar_evolution import native_trusted_scheduler as native
from lunar_evolution import rsi_brs_native_provider as brs
from lunar_evolution import rsi_native_scheduler as scheduler
from lunar_evolution import rsi_python_scheduler_inputs as python_inputs
from lunar_evolution.native_fixed_live_sink import (
    NativeFixedLiveSinkError,
    _pin_fixed_python_live_sink_request,
)
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _selected_context(context, request):
    intent = replace(context.intent, executable_sha256=hashlib.sha256(request.image).hexdigest(),
                     intent_sha256=None)
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = build_producer_launch_attestation(intent, "inert-live-sink-routing")
    return replace(context, intent=intent, attestation=attestation, live_modules_sink=request)


def _native_context(tmp_path):
    value = _context(tmp_path)
    return NativeRSISchedulerContext(
        tmp_path, tmp_path / "producer", value.intent, value.attestation, value.artifact,
        value.broker, value.contract, (BundleGroup("candidate", "main.py", ("main.py",)),),
        "local", "e" * 64, "f" * 64, "1" * 64, "2" * 64, object(),
    )


@pytest.mark.parametrize("field", ["image", "runtime_main_source", "source_profile",
                                   "expected_installation_sha256", "installation"])
def test_selected_context_refuses_request_field_replacement_and_does_not_repin(tmp_path, field):
    request, _ = _request_vector()
    context = _selected_context(_native_context(tmp_path), request)
    before = context._live_modules_sink_pin
    value = getattr(request, field)
    changed = (replace(value) if field == "installation" else b"changed" if type(value) is bytes
               else "changed")
    object.__setattr__(request, field, changed)
    for operation in (context._assert_live_modules_sink, context.__post_init__):
        with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
            operation()
    assert context._live_modules_sink_pin is before


def test_selected_context_refuses_equivalent_new_request_and_nested_installation_mutation(tmp_path):
    request, _ = _request_vector()
    context = _selected_context(_native_context(tmp_path), request)
    object.__setattr__(context, "live_modules_sink", replace(request))
    with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
        context._assert_live_modules_sink()
    object.__setattr__(context, "live_modules_sink", request)
    object.__setattr__(request.installation, "frozen_names", request.installation.frozen_names + ("drift",))
    with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
        context._assert_live_modules_sink()


@pytest.mark.parametrize("selected", [False, True])
def test_context_projection_is_opt_in_and_copies_preserve_original_sink(tmp_path, monkeypatch, selected):
    request, _ = _request_vector()
    plain = _native_context(tmp_path)
    context = _selected_context(plain, request) if selected else plain
    monkeypatch.setattr(scheduler, "_strategy_fingerprint", lambda *_a: "a" * 64)
    projection = NativeRSISchedulerProvider(context).rsi_fingerprint_config()
    assert ("live_modules_sink" in projection) is selected
    if selected:
        assert projection["live_modules_sink"]["image_sha256"] == hashlib.sha256(request.image).hexdigest()
        assert projection["live_modules_sink"]["production_admission"] is False
    for copied in (replace(context), replace(context, workspace=str(tmp_path))):
        assert copied._assert_live_modules_sink() is (request if selected else None)
        assert copied._live_modules_sink_projection() == context._live_modules_sink_projection()
    object.__setattr__(context, "live_modules_sink", None if selected else request)
    with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
        context.__post_init__()


@pytest.mark.parametrize("fault", ["replace", "remove", "insert", "installation"])
def test_provider_rejects_sink_drift_before_original_native_input_reader(tmp_path, monkeypatch, fault):
    request, _ = _request_vector()
    context = _native_context(tmp_path)
    if fault != "insert":
        context = _selected_context(context, request)
    provider = NativeRSISchedulerProvider(context)
    if fault == "installation":
        object.__setattr__(request.installation, "aliases", request.installation.aliases + (("x", "y"),))
    else:
        object.__setattr__(context, "live_modules_sink", None if fault == "remove" else replace(request))
    touched = []

    def forbidden(*_a, **_kw):
        touched.append("reader")
        raise AssertionError("original input reader must follow sink drift gate")

    monkeypatch.setattr(scheduler, "validate_native_rsi_launch_inputs", forbidden)
    with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
        provider._inputs(require_unexpired=True)
    assert touched == []


def test_sink_pin_rejects_wrong_original_target_digest_and_foreign_field_shapes():
    request, _ = _request_vector()
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        _pin_fixed_python_live_sink_request(request, target_sha256="b" * 64)
    object.__setattr__(request, "image", bytearray(request.image))
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        _pin_fixed_python_live_sink_request(request, target_sha256="a" * 64)


@pytest.mark.parametrize("wrapper", [native.run_native_trusted_producer,
                                     native.run_native_trusted_producer_outcome,
                                     native._prepare_native_trusted_python_producer])
@pytest.mark.parametrize("selected", [False, True])
def test_all_original_scheduler_wrappers_preserve_exact_sink_and_default_call_shape(
    tmp_path, monkeypatch, wrapper, selected,
):
    value, (request, _) = _context(tmp_path), _request_vector()
    seen = []
    sentinel = object()

    def core(*args, **options):
        seen.append(options)
        return sentinel

    monkeypatch.setattr(native, "_run_native_trusted_producer", core)
    options = {"producer_root": tmp_path, "intent": value.intent, "attestation": value.attestation,
        "artifact": value.artifact, "broker_config": value.broker, "contract": value.contract, "groups": (),
        "evaluator_kind": "local", "evaluator_fingerprint": "e" * 64, "runner_fingerprint": "f" * 64,
        "dependency_sha256": "1" * 64, "environment_sha256": "2" * 64,
        "parent_deadline": 123.5, "execution_control": None, "cancelled": None}
    if wrapper is native._prepare_native_trusted_python_producer:
        options.update(python_handoff_after_execution=lambda *_a: None, evidence_revalidator=lambda *_a: None)
    if selected:
        options["live_modules_sink"] = request
    assert wrapper(value.workspace, **options) is sentinel
    assert len(seen) == 1 and seen[0]["parent_deadline"] == 123.5
    assert ("live_modules_sink" in seen[0]) is selected
    if selected:
        assert seen[0]["live_modules_sink"] is request


@pytest.mark.parametrize("selected", [False, True])
def test_original_scheduler_passes_sink_to_its_only_attempt_preserving_receipt_order(
    tmp_path, monkeypatch, selected,
):
    value, (request, _) = _context(tmp_path), _request_vector()
    events = []
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256=receipt.receipt_sha256,
                             drafts=("draft",), admission_plan="plan")

    def attempt(*_a, **options):
        events.append("attempt")
        assert ("live_modules_sink" in options) is selected
        if selected:
            assert options["live_modules_sink"] is request
        assert options["intent"] is value.intent and options["attestation"] is value.attestation
        return _attempt()

    monkeypatch.setattr(native, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(native, "persist_native_trusted_execution_receipt",
                        lambda *_a, **_kw: events.append("receipt") or receipt)
    monkeypatch.setattr(native, "prepare_native_trusted_output",
                        lambda *_a, **_kw: events.append("output") or output)
    result = native.run_native_trusted_producer(value.workspace, producer_root=tmp_path,
        intent=value.intent, attestation=value.attestation, artifact=value.artifact,
        broker_config=value.broker, contract=value.contract, groups=(), evaluator_kind="local",
        evaluator_fingerprint="e" * 64, runner_fingerprint="f" * 64, dependency_sha256="1" * 64,
        environment_sha256="2" * 64, **({"live_modules_sink": request} if selected else {}))
    assert events == ["attempt", "receipt", "output"]
    assert result.receipt is receipt and result.output is output


def test_python_native_normalization_preserves_exact_selected_sink_and_catches_original_drift(tmp_path):
    # Only the local normalization seam consumes this explicit inert binding view;
    # it is never passed to a gateway, stager or reader as a valid producer binding.
    value = _setup(tmp_path)
    request, _ = _request_vector()
    context = _selected_context(value.native, request)
    binding = SimpleNamespace(intent=context.intent, attestation=context.attestation,
        intent_sha256=context.intent.digest(), attestation_sha256=context.attestation.digest(),
        contract_sha256=context.contract.digest(), evaluator_kind=context.evaluator_kind,
        evaluator_fingerprint=context.evaluator_fingerprint, dependency_sha256=context.dependency_sha256,
        environment_sha256=context.environment_sha256, runtime_manifest=value.binding.runtime_manifest,
        interpreter=value.binding.interpreter)
    copied = python_inputs._native(context, binding)
    assert copied is not context and copied.live_modules_sink is request
    assert copied._assert_live_modules_sink() is request
    object.__setattr__(context, "live_modules_sink", replace(request))
    with pytest.raises(python_inputs.PythonRSISchedulerInputError, match="native_context_drift"):
        python_inputs._native(context, binding)


@pytest.mark.parametrize("selected", [False, True])
def test_ordinary_provider_preserves_sink_to_original_scheduler_before_any_result_mapping(
    tmp_path, monkeypatch, selected,
):
    value = _setup(tmp_path)
    request, _ = _request_vector()
    context = _selected_context(value.native, request) if selected else value.native
    provider = NativeRSISchedulerProvider(context)
    plan = NativeRSIExecutionPlan.from_native_inputs(inputs=value.descriptor, request=value.request,
        memory=value.memory, intent=context.intent, attestation=context.attestation,
        artifact=context.artifact, candidate_selector_id="native-selector-v1",
        candidate_selector_sha256="a" * 64, evaluator_kind=context.evaluator_kind,
        evaluator_fingerprint=context.evaluator_fingerprint)
    monkeypatch.setattr(provider, "_inputs", lambda **_kw: value.descriptor)
    monkeypatch.setattr(provider, "_python_publication_join", lambda *_a: {})
    monkeypatch.setattr(scheduler, "_assert_plan_binding", lambda *_a: None)
    monkeypatch.setattr(scheduler, "_memory_from_request_inputs", lambda *_a: value.memory)
    seen = []

    def dispatch(*_a, **options):
        seen.append(options)
        raise NativeRSISchedulerProviderError("inert_dispatch_stop")

    monkeypatch.setattr(scheduler, "run_native_trusted_producer", dispatch)
    with pytest.raises(NativeRSISchedulerProviderError, match="inert_dispatch_stop"):
        provider(value.request, plan)
    assert len(seen) == 1 and ("live_modules_sink" in seen[0]) is selected
    if selected:
        assert seen[0]["live_modules_sink"] is request
    assert seen[0]["execution_control"] is context.execution_control
    assert seen[0]["cancelled"] is context.cancelled


def test_reserved_brs_worker_passes_exact_sink_through_original_preparation_exchange(binding_fixture):
    value = binding_fixture
    request, _ = _request_vector()
    value.provider.context = _selected_context(value.provider.context, request)
    original, seen = brs._prepare_native_trusted_python_producer, []

    def prepare(*args, **options):
        seen.append(options["live_modules_sink"])
        return original(*args, **options)

    value.monkeypatch.setattr(brs, "_prepare_native_trusted_python_producer", prepare)
    _published_components(value)
    _inert_endpoint(value)
    bound = _bind(value)
    _claim(value)
    _run_with_original_exchange(value)
    assert seen == [request] and seen[0] is request
    assert bound._state == "returned" and value.scope.exchange._state == "consumed"


def test_reserved_brs_hot_gate_rejects_equivalent_sink_replacement_before_prepare(binding_fixture):
    value = binding_fixture
    request, _ = _request_vector()
    value.provider.context = _selected_context(value.provider.context, request)
    bound = _bind(value)
    object.__setattr__(value.provider.context, "live_modules_sink", replace(request))
    with pytest.raises(NativeRSISchedulerProviderError, match="live_modules_sink_changed"):
        brs._BRSNativeProviderBinding._fixed(bound, value.request, value.native_plan)
    assert not any(event[0] == "prepare" for event in value.events)
