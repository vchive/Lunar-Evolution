"""Borrowed original scope/config routing with explicitly inert effects.

The private-token scope and patched installed check are synthetic fixtures. They
do not acquire root, run a target or establish build/runtime/pycache acceptance.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_scheduler import _attempt
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
from test_rsi_live_sink_scheduler import _native_context
from test_rsi_python_brs_publication_inputs import prepared as prepared  # noqa: PLC0414
from test_rsi_python_scheduler_inputs import _setup

from lunar_evolution import native_trusted_scheduler as native
from lunar_evolution import native_whole_scope as whole
from lunar_evolution import rsi_brs_native_provider as brs
from lunar_evolution import rsi_native_scheduler as scheduler
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.native_pycache_diagnostic import NativePycacheDiagnosticRequest
from lunar_evolution.native_trusted_attempt import NativeTrustedAttemptError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _observer(*_args):
    return None


def _linux_context(context):
    artifact = replace(context.artifact, platform_execution_mode="linux-fd-bound",
                       descriptor=replace(context.artifact.descriptor,
                                          platform_execution_mode="linux-fd-bound"))
    return replace(context, artifact=artifact)


def _scope(context, monkeypatch):
    # No actual installation is claimed by this finite routing fixture.
    scope = whole.NativeWholeScopeOwner(whole._TOKEN)
    scope._profile_raw = b"inert-native-scheduler-scope-profile"
    scope._profile_sha256 = hashlib.sha256(scope._profile_raw).hexdigest()
    scope._profile = {"bootstrap_sha256": context.artifact.artifact_sha256}
    scope._preparation_key = "original-scope"
    scope._inert_journal = context.intent.journal_id
    scope._deadline = time.monotonic_ns() + 60_000_000_000

    def installed(original):
        if original._closed:
            raise whole.NativeWholeScopeError("inert_original_closed")

    monkeypatch.setattr(whole.NativeWholeScopeOwner, "_check_published_grants", installed)
    monkeypatch.setattr(whole.NativeWholeScopeOwner, "journal_id",
                        property(lambda original: original._inert_journal))
    return scope


def _selected(context, monkeypatch, selection="both"):
    context = _linux_context(context)
    scope = _scope(context, monkeypatch) if selection in {"scope", "both"} else None
    diagnostic = NativePycacheDiagnosticRequest(_observer) if selection in {"diagnostic", "both"} else None
    return replace(context, whole_scope=scope, pycache_diagnostic=diagnostic), scope, diagnostic


def _options(context):
    return {
        "producer_root": context.producer_root, "intent": context.intent,
        "attestation": context.attestation, "artifact": context.artifact,
        "broker_config": context.broker_config, "contract": context.contract,
        "groups": context.groups, "evaluator_kind": context.evaluator_kind,
        "evaluator_fingerprint": context.evaluator_fingerprint,
        "runner_fingerprint": context.runner_fingerprint,
        "dependency_sha256": context.dependency_sha256,
        "environment_sha256": context.environment_sha256,
    }


def _plan(value, context):
    return NativeRSIExecutionPlan.from_native_inputs(
        inputs=value.descriptor, request=value.request, memory=value.memory,
        intent=context.intent, attestation=context.attestation, artifact=context.artifact,
        candidate_selector_id="native-selector-v1", candidate_selector_sha256="a" * 64,
        evaluator_kind=context.evaluator_kind, evaluator_fingerprint=context.evaluator_fingerprint,
    )


@pytest.mark.parametrize("selection", ("none", "scope", "diagnostic", "both"))
def test_context_selection_projection_and_copies_preserve_originals(tmp_path, monkeypatch, selection):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch, selection)
    monkeypatch.setattr(scheduler, "_strategy_fingerprint", lambda *_args: "a" * 64)
    projection = NativeRSISchedulerProvider(context).rsi_fingerprint_config()
    assert ("native_scope" in projection) is (selection != "none")
    pin = context._native_scope_pin
    context.__post_init__()
    assert context._native_scope_pin is pin
    for copied in (replace(context), replace(context, workspace=str(tmp_path))):
        options = copied._native_scope_options()
        assert copied.whole_scope is scope and copied.pycache_diagnostic is diagnostic
        assert ("whole_scope" in options) is (scope is not None)
        assert ("pycache_diagnostic" in options) is (diagnostic is not None)
        assert copied._native_scope_projection() == context._native_scope_projection()


@pytest.mark.parametrize("field", ("whole_scope", "pycache_diagnostic"))
@pytest.mark.parametrize("foreign", (object(), {}))
def test_context_refuses_foreign_scope_config_before_any_attempt(tmp_path, monkeypatch, field, foreign):
    context = _linux_context(_native_context(tmp_path))
    attempts = []
    monkeypatch.setattr(native, "run_native_trusted_attempt", lambda *_a, **_kw: attempts.append(True))
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_invalid"):
        replace(context, **{field: foreign})
    assert attempts == []


@pytest.mark.parametrize("fault", ("remove_scope", "replace_scope", "remove_diagnostic", "replace_diagnostic"))
def test_context_rejects_replacement_without_repinning(tmp_path, monkeypatch, fault):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    pin = context._native_scope_pin
    if fault.endswith("scope"):
        object.__setattr__(context, "whole_scope", None if fault.startswith("remove") else _scope(context, monkeypatch))
    else:
        object.__setattr__(context, "pycache_diagnostic", None if fault.startswith("remove") else replace(diagnostic))
    for operation in (context._native_scope_options, context.__post_init__):
        with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
            operation()
    assert context._native_scope_pin is pin and pin.whole_scope is scope


@pytest.mark.parametrize("field", ("observer", "diagnostic_profile", "working_directories", "output_directories"))
def test_diagnostic_same_value_field_replacement_is_drift_before_input_read(tmp_path, monkeypatch, field):
    context, _scope_owner, diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    original = getattr(diagnostic, field)
    changed = (lambda *_args: None) if field == "observer" else (
        ("x" + original)[1:] if type(original) is str else (*original,)
    )
    assert changed is not original
    object.__setattr__(diagnostic, field, changed)
    reads = []
    monkeypatch.setattr(scheduler, "validate_native_rsi_launch_inputs", lambda *_a, **_kw: reads.append(True))
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        NativeRSISchedulerProvider(context)._inputs(require_unexpired=True)
    assert reads == []


@pytest.mark.parametrize("fault", ("closed", "journal", "profile", "profile_content", "deadline_extension"))
def test_original_scope_mutation_refuses_before_native_input_read(tmp_path, monkeypatch, fault):
    context, scope, _diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    if fault == "closed":
        scope._closed = True
    elif fault == "journal":
        scope._inert_journal = "foreign"
    elif fault == "profile":
        scope._profile_sha256 = "f" * 64
    elif fault == "profile_content":
        scope._profile["uid"] = 0
    else:
        scope._deadline += 1
    reads = []
    monkeypatch.setattr(scheduler, "validate_native_rsi_launch_inputs", lambda *_a, **_kw: reads.append(True))
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        NativeRSISchedulerProvider(context)._inputs(require_unexpired=True)
    assert reads == []


def test_shortened_deadline_and_terminal_state_preserve_fingerprint_without_relaunch(tmp_path, monkeypatch):
    context, scope, _diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    projection = context._native_scope_projection()
    scope._deadline -= 1_000_000
    scope._released = scope._finished = True
    assert context._native_scope_projection() == projection
    assert context._native_scope_options()["whole_scope"] is scope
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        context._native_scope_options(require_unexpired=True)


def test_historical_scope_check_never_renews_expired_original_budget(tmp_path, monkeypatch):
    context, scope, _diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    original_bound = context._native_scope_pin.scope_fields[-1]
    scope._deadline = time.monotonic_ns() - 1
    assert context._native_scope_options()["whole_scope"] is scope
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        context._native_scope_options(require_unexpired=True)
    assert scope.deadline_ns < original_bound


@pytest.mark.parametrize("wrapper", (native.run_native_trusted_producer,
                                     native.run_native_trusted_producer_outcome,
                                     native._prepare_native_trusted_python_producer))
@pytest.mark.parametrize("selected", (False, True))
def test_all_wrappers_keep_default_shape_and_forward_originals(tmp_path, monkeypatch, wrapper, selected):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    seen, sentinel = [], object()
    monkeypatch.setattr(native, "_run_native_trusted_producer",
                        lambda *_args, **options: seen.append(options) or sentinel)
    options = _options(context)
    if selected:
        options.update(whole_scope=scope, pycache_diagnostic=diagnostic)
    if wrapper is native._prepare_native_trusted_python_producer:
        options.update(python_handoff_after_execution=_observer, evidence_revalidator=_observer)
    assert wrapper(context.workspace, **options) is sentinel
    assert len(seen) == 1
    assert ("whole_scope" in seen[0]) is selected
    assert ("pycache_diagnostic" in seen[0]) is selected
    if selected:
        assert seen[0]["whole_scope"] is scope and seen[0]["pycache_diagnostic"] is diagnostic


@pytest.mark.parametrize("selection", ("none", "scope", "diagnostic", "both"))
def test_only_original_attempt_receives_selected_objects_and_keeps_receipt_order(tmp_path, monkeypatch, selection):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch, selection)
    events = []
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256=receipt.receipt_sha256)

    def attempt(*_args, **options):
        events.append("attempt")
        assert ("whole_scope" in options) is (scope is not None)
        assert ("pycache_diagnostic" in options) is (diagnostic is not None)
        if scope is not None:
            assert options["whole_scope"] is scope
        if diagnostic is not None:
            assert options["pycache_diagnostic"] is diagnostic
        return _attempt()

    monkeypatch.setattr(native, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(native, "persist_native_trusted_execution_receipt",
                        lambda *_a, **_kw: events.append("receipt") or receipt)
    monkeypatch.setattr(native, "prepare_native_trusted_output",
                        lambda *_a, **_kw: events.append("output") or output)
    result = native.run_native_trusted_producer(
        context.workspace, **_options(context), **context._native_scope_options(),
    )
    assert events == ["attempt", "receipt", "output"]
    assert result.receipt is receipt and result.output is output
    if scope is not None:
        assert not scope._closed


@pytest.mark.parametrize("field", ("whole_scope", "pycache_diagnostic"))
def test_direct_scheduler_rejects_wrong_scope_before_attempt(tmp_path, monkeypatch, field):
    context = _linux_context(_native_context(tmp_path))
    attempts = []
    monkeypatch.setattr(native, "run_native_trusted_attempt", lambda *_a, **_kw: attempts.append(True))
    with pytest.raises(native.NativeTrustedSchedulerError, match="scope_invalid"):
        native.run_native_trusted_producer(context.workspace, **_options(context), **{field: object()})
    assert attempts == []


@pytest.mark.parametrize("terminal", ("unknown", "failure"))
def test_failed_or_unknown_attempt_preserves_original_scope_without_retry(tmp_path, monkeypatch, terminal):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    attempts, sentinel = [], object()

    def attempt(*_args, **options):
        attempts.append(options)
        assert options["whole_scope"] is scope and options["pycache_diagnostic"] is diagnostic
        if terminal == "unknown":
            raise NativeTrustedAttemptError("native_trusted_attempt_terminal_receipt_missing")
        return replace(_attempt(), exit_code=1)

    monkeypatch.setattr(native, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(native, "build_native_trusted_failure", lambda *_a, **_kw: sentinel)
    if terminal == "unknown":
        with pytest.raises(native.NativeTrustedSchedulerError, match="attempt_failed"):
            native.run_native_trusted_producer_outcome(
                context.workspace, **_options(context), **context._native_scope_options(),
            )
    else:
        assert native.run_native_trusted_producer_outcome(
            context.workspace, **_options(context), **context._native_scope_options(),
        ) is sentinel
    assert len(attempts) == 1 and not scope._closed
    assert context.whole_scope is scope and context.pycache_diagnostic is diagnostic


@pytest.mark.parametrize("stage", ("native_producer_after_attempt", "native_producer_after_output"))
def test_direct_scheduler_rechecks_original_config_after_stage_observer(tmp_path, monkeypatch, stage):
    context, scope, diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    events = []
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256=receipt.receipt_sha256)

    def observe(current):
        if current == stage:
            object.__setattr__(diagnostic, "observer", lambda *_args: None)

    monkeypatch.setattr(native, "run_native_trusted_attempt", lambda *_a, **_kw: events.append("attempt") or _attempt())
    monkeypatch.setattr(native, "persist_native_trusted_execution_receipt",
                        lambda *_a, **_kw: events.append("receipt") or receipt)
    monkeypatch.setattr(native, "prepare_native_trusted_output",
                        lambda *_a, **_kw: events.append("output") or output)
    with pytest.raises(native.NativeTrustedSchedulerError, match="scope_invalid"):
        native.run_native_trusted_producer(
            context.workspace, **_options(context), **context._native_scope_options(),
            execution_control=SolveExecutionControl(10, observe_stage=observe),
        )
    assert events == (["attempt"] if stage.endswith("after_attempt") else ["attempt", "receipt", "output"])
    assert not scope._closed


def test_ordinary_provider_passes_originals_before_unknown_result(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    context, scope, diagnostic = _selected(value.native, monkeypatch)
    provider, plan = NativeRSISchedulerProvider(context), _plan(value, context)
    monkeypatch.setattr(provider, "_inputs", lambda **_kw: value.descriptor)
    monkeypatch.setattr(provider, "_python_publication_join", lambda *_a: {})
    monkeypatch.setattr(scheduler, "_assert_plan_binding", lambda *_a: None)
    monkeypatch.setattr(scheduler, "_memory_from_request_inputs", lambda *_a: value.memory)
    seen = []

    def dispatch(*_args, **options):
        seen.append(options)
        raise NativeRSISchedulerProviderError("inert_unknown_result")

    monkeypatch.setattr(scheduler, "run_native_trusted_producer", dispatch)
    with pytest.raises(NativeRSISchedulerProviderError, match="inert_unknown_result"):
        provider(value.request, plan)
    assert len(seen) == 1
    assert seen[0]["whole_scope"] is scope and seen[0]["pycache_diagnostic"] is diagnostic
    assert context.whole_scope is scope and not scope._closed


def test_existing_native_input_reader_gets_only_original_fixed_u_child(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    fixed_owner, seen = object(), []
    monkeypatch.setattr(whole.NativeWholeScopeOwner, "original_fixed_u_input_owner",
                        property(lambda _original: fixed_owner))
    context, _scope_owner, _diagnostic = _selected(value.native, monkeypatch)
    monkeypatch.setattr(scheduler, "validate_native_rsi_launch_inputs",
                        lambda *_a, **options: seen.append(options) or value.descriptor)
    assert NativeRSISchedulerProvider(context)._inputs(require_unexpired=False) is value.descriptor
    assert len(seen) == 1 and seen[0]["fixed_u_owner"] is fixed_owner
    assert seen[0]["require_unexpired"] is False


@pytest.mark.parametrize("child", ("original_fixed_u_input_owner", "original_custody_owner"))
def test_scope_cannot_acquire_new_child_authority_after_context_freeze(tmp_path, monkeypatch, child):
    context, _scope_owner, _diagnostic = _selected(_native_context(tmp_path), monkeypatch)
    original_child = object()
    monkeypatch.setattr(whole.NativeWholeScopeOwner, child, property(lambda _owner: original_child))
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        context._native_scope_options()


def test_reserved_brs_passes_original_scope_config_through_same_exchange(binding_fixture):
    value = binding_fixture
    context, scope, diagnostic = _selected(value.provider.context, value.monkeypatch)
    value.provider.context = context
    original, seen = brs._prepare_native_trusted_python_producer, []

    def prepare(*args, **options):
        seen.append(options)
        return original(*args, **options)

    value.monkeypatch.setattr(brs, "_prepare_native_trusted_python_producer", prepare)
    _published_components(value)
    _inert_endpoint(value)
    bound = _bind(value)
    _claim(value)
    _run_with_original_exchange(value)
    assert len(seen) == 1
    assert seen[0]["whole_scope"] is scope and seen[0]["pycache_diagnostic"] is diagnostic
    assert bound._state == "returned" and value.scope.exchange._state == "consumed"
    assert not scope._closed


def test_reserved_brs_refuses_replaced_scope_before_preparation(binding_fixture):
    value = binding_fixture
    context, _scope_owner, diagnostic = _selected(value.provider.context, value.monkeypatch)
    value.provider.context = context
    bound = _bind(value)
    object.__setattr__(context, "pycache_diagnostic", replace(diagnostic))
    with pytest.raises(NativeRSISchedulerProviderError, match="native_scope_changed"):
        brs._BRSNativeProviderBinding._fixed(bound, value.request, value.native_plan)
    assert not any(event[0] == "prepare" for event in value.events)
