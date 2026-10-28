"""Opt-in provider wiring keeps late evidence behind native execution."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_scheduler import _context
from test_rsi_native_scheduler_prepared_boundary import _provider
from test_rsi_python_admission import _setup
from test_static_python_fixed_runtime_observation import _runtime_vector

from lunar_evolution.native_trusted_scheduler import NativeTrustedProducerRun
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.python_producer_admission_handoff import PythonProducerAdmissionHandoffSidecar
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _supplier_a(_receipt, _output):
    raise AssertionError("inert supplier must not run before native dispatch")


def _supplier_b(_receipt, _output):
    raise AssertionError("a different inert supplier must not run before dispatch")


def _strategy_fixture():
    return None


def _native_supplier_a(_run):
    raise AssertionError("inert native supplier must not run before native preparation")


def _native_supplier_b(_run):
    raise AssertionError("a different native supplier must not run before native preparation")


def _native_context(tmp_path, supplier=_native_supplier_a):
    value = _context(tmp_path)
    sink, _payload = _runtime_vector()
    intent = replace(value.intent, executable_sha256=hashlib.sha256(sink.image).hexdigest(), intent_sha256=None)
    return NativeRSISchedulerContext(
        workspace=value.workspace, producer_root=value.workspace, intent=intent,
        attestation=build_producer_launch_attestation(intent, "native-hook-once"),
        artifact=value.artifact, broker_config=value.broker, contract=value.contract,
        groups=(BundleGroup("candidate", "solve.py", ("solve.py",)),), evaluator_kind="local",
        evaluator_fingerprint="a" * 64, runner_fingerprint="a" * 64,
        dependency_sha256="a" * 64, environment_sha256="a" * 64, strategy=_strategy_fixture,
        live_modules_sink=sink, python_handoff_after_native_execution=supplier,
    )


def _configured_provider(value, supplier=None):
    provider = _provider(value)
    original = provider.context
    provider.context = SimpleNamespace(
        **{field: getattr(original, field) for field in (
            "workspace", "intent", "attestation", "artifact", "contract", "evaluator_kind",
            "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256",
        )},
        producer_root=value.workspace, broker_config=ProducerBrokerConfig("http://127.0.0.1:1", {}),
        groups=(), strategy=_strategy_fixture, execution_control=None, cancelled=None,
        failure_ledger=None, python_handoff_after_execution=supplier,
        live_modules_sink=None, _live_modules_sink_pin=None,
    )
    provider._failure_ledger_identity = None
    return provider


def test_enabled_dispatch_passes_only_lazy_hooks_before_prepared_files(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _configured_provider(value, _supplier_a)
    for name in ("parse_producer_bundle_publication_journal",
                 "read_python_producer_admission_attempt_anchor",
                 "read_python_producer_admission_handoff_pinned"):
        monkeypatch.setattr(
            "lunar_evolution.rsi_native_scheduler." + name,
            lambda *_args, **_kwargs: pytest.fail("dispatch read late prepared evidence"),
        )
    calls = []

    def stop(*_args, **kwargs):
        calls.append(kwargs)
        assert all(callable(kwargs[key]) for key in (
            "python_handoff_after_execution", "prepared_observer", "evidence_revalidator",
        ))
        raise ValueError("inert stop before producer execution")

    monkeypatch.setattr("lunar_evolution.rsi_native_scheduler.run_native_trusted_producer", stop)
    with pytest.raises(NativeRSISchedulerProviderError, match="attempt_failed"):
        provider(value.request, value.plan)
    assert len(calls) == 1


def test_disabled_dispatch_does_not_forward_python_options(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _configured_provider(value)

    def stop(*_args, **kwargs):
        assert not {"python_handoff_after_execution", "prepared_observer",
                    "evidence_revalidator"}.intersection(kwargs)
        raise ValueError("inert stop before producer execution")

    monkeypatch.setattr("lunar_evolution.rsi_native_scheduler.run_native_trusted_producer", stop)
    with pytest.raises(NativeRSISchedulerProviderError, match="attempt_failed"):
        provider(value.request, value.plan)


def test_supplier_is_fingerprinted_only_when_explicitly_enabled(tmp_path):
    value = _setup(tmp_path)
    provider = _configured_provider(value)
    disabled = provider.rsi_fingerprint_config()
    assert "python_handoff_after_execution_sha256" not in disabled
    provider.context.python_handoff_after_execution = _supplier_a
    enabled = provider.rsi_fingerprint_config()
    assert enabled.pop("python_handoff_after_execution_sha256") == component_fingerprint(_supplier_a)
    assert enabled == disabled
    provider.context.python_handoff_after_execution = _supplier_b
    assert provider.rsi_fingerprint_config()["python_handoff_after_execution_sha256"] != component_fingerprint(_supplier_a)
    provider.context.python_handoff_after_execution = None
    assert provider.rsi_fingerprint_config() == disabled


@pytest.mark.parametrize("mutation", ["controller", "sidecar", "workspace", "wait_check"])
def test_missing_original_controller_wiring_refuses_before_dispatch(tmp_path, monkeypatch, mutation):
    value = _setup(tmp_path)
    provider = _configured_provider(value, _supplier_a)
    if mutation == "controller":
        provider._python_admission_controller = None
    elif mutation == "sidecar":
        value.controller.producer_sidecar = None
    elif mutation == "workspace":
        value.controller.producer_workspace = value.workspace / "foreign"
    else:
        value.controller._python_admission_bridge_wait_check = None
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer",
        lambda *_args, **_kwargs: pytest.fail("missing controller wiring dispatched producer"),
    )
    with pytest.raises(NativeRSISchedulerProviderError, match="python_admission"):
        provider(value.request, value.plan)


def test_success_return_without_prepared_ack_refuses_before_receipt_projection(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _configured_provider(value, _supplier_a)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler._build_receipts",
        lambda *_args, **_kwargs: pytest.fail("unacknowledged join projected receipts"),
    )
    with pytest.raises(NativeRSISchedulerProviderError, match="python_admission_missing"):
        provider(value.request, value.plan)


def test_postexecution_supplier_requires_an_active_owner_scope(tmp_path):
    value = _setup(tmp_path)
    provider = _configured_provider(value, _supplier_a)
    hooks = provider._python_publication_join(
        value.request, value.plan, provider._inputs(require_unexpired=False),
    )
    with pytest.raises(ValueError, match="bridge_worker_missing"):
        hooks["python_handoff_after_execution"](object(), object())
    with pytest.raises(NativeRSISchedulerProviderError, match="python_handoff_supplier_replayed"):
        hooks["python_handoff_after_execution"](object(), object())


def test_observer_without_original_supplier_evidence_refuses(tmp_path):
    value = _setup(tmp_path)
    provider = _configured_provider(value, _supplier_a)
    hooks = provider._python_publication_join(
        value.request, value.plan, provider._inputs(require_unexpired=False),
    )
    with pytest.raises(NativeRSISchedulerProviderError, match="python_handoff_supplier_missing"):
        hooks["prepared_observer"](value.journal)
    with pytest.raises(NativeRSISchedulerProviderError, match="prepared_observer_replayed"):
        hooks["prepared_observer"](value.journal)


def test_context_rejects_noncallable_supplier_before_other_launch_inputs(tmp_path):
    value = _context(tmp_path)
    with pytest.raises(NativeRSISchedulerProviderError, match="python_handoff_supplier_invalid"):
        NativeRSISchedulerContext(
            workspace=value.workspace, producer_root=value.workspace, intent=value.intent,
            attestation=value.attestation, artifact=value.artifact, broker_config=value.broker,
            contract=value.contract, groups=(), evaluator_kind="local",
            evaluator_fingerprint="a" * 64, runner_fingerprint="a" * 64,
            dependency_sha256="a" * 64, environment_sha256="a" * 64,
            strategy=object(), python_handoff_after_execution="invalid",
        )


def test_context_freezes_supplier_in_original_immutable_wiring(tmp_path):
    # Reuse the inert public context from the existing native e2e fixture without
    # running that fixture's producer, broker or evaluator.
    from lunar_evolution.producer_bundle_handoff import BundleGroup

    value = _context(tmp_path)
    context = NativeRSISchedulerContext(
        workspace=value.workspace, producer_root=value.workspace, intent=value.intent,
        attestation=value.attestation, artifact=value.artifact, broker_config=value.broker,
        contract=value.contract, groups=(BundleGroup("candidate", "solve.py", ("solve.py",)),),
        evaluator_kind="local", evaluator_fingerprint="a" * 64, runner_fingerprint="a" * 64,
        dependency_sha256="a" * 64, environment_sha256="a" * 64, strategy=object(),
        python_handoff_after_execution=_supplier_a,
    )
    assert context.python_handoff_after_execution is _supplier_a
    assert replace(context, python_handoff_after_execution=_supplier_b).python_handoff_after_execution is _supplier_b
    with pytest.raises(AttributeError):
        context.python_handoff_after_execution = _supplier_b


def test_native_supplier_is_explicitly_fingerprinted_with_its_evidence_helpers(tmp_path):
    context = _native_context(tmp_path)
    provider = NativeRSISchedulerProvider(context)
    enabled = provider.rsi_fingerprint_config()
    assert enabled.pop("python_handoff_after_native_execution_sha256") == component_fingerprint(_native_supplier_a)
    assert set(enabled.pop("python_native_handoff_dependencies")) == {
        "evidence", "preparation_evidence", "scheduler", "supplier_selection", "late_join",
    }
    provider.context = replace(context, python_handoff_after_native_execution=None)
    assert provider.rsi_fingerprint_config() == enabled
    provider.context = replace(context, python_handoff_after_native_execution=_native_supplier_b)
    assert provider.rsi_fingerprint_config()["python_handoff_after_native_execution_sha256"] != component_fingerprint(
        _native_supplier_a,
    )
    with pytest.raises(AttributeError):
        context.python_handoff_after_native_execution = _native_supplier_b


@pytest.mark.parametrize("helper", ["_native_handoff_evidence", "_prepublication_evidence", "_run_native_trusted_producer"])
def test_native_module_helper_rebinding_refuses_even_when_imported_alias_is_unchanged(tmp_path, monkeypatch, helper):
    provider = NativeRSISchedulerProvider(_native_context(tmp_path))
    provider.rsi_fingerprint_config()
    monkeypatch.setattr("lunar_evolution.native_trusted_scheduler." + helper, lambda *_a: None)
    with pytest.raises(NativeRSISchedulerProviderError, match="native_handoff_policy_changed"):
        provider.rsi_fingerprint_config()


@pytest.mark.parametrize("mutation", ["both", "missing_sink", "noncallable"])
def test_native_context_configuration_refuses_before_launch(tmp_path, mutation):
    context = _native_context(tmp_path)
    changes = {"both": {"python_handoff_after_execution": _supplier_a},
               "missing_sink": {"live_modules_sink": None},
               "noncallable": {"python_handoff_after_native_execution": "invalid"}}[mutation]
    with pytest.raises(NativeRSISchedulerProviderError, match="supplier|native_sink_required"):
        replace(context, **changes)


def test_native_late_join_forwards_exact_run_once_without_reading_prepared_files(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _configured_provider(value)
    retained = PythonProducerAdmissionHandoffSidecar(value.handoff, value.pin)
    run = NativeTrustedProducerRun(object(), object(), SimpleNamespace(admission_plan=object()))
    received = []

    def supplier(observed):
        received.append(observed)
        return retained

    provider.context.python_handoff_after_native_execution = supplier
    provider.context.live_modules_sink = object()  # Lower native tests exercise the actual sink gate.
    monkeypatch.setattr(value.controller, "_python_admission_bridge_wait_check", lambda: None)
    monkeypatch.setattr(type(value.controller), "_python_admission_brs_observations", lambda _self: nullcontext())
    monkeypatch.setattr("lunar_evolution.rsi_native_scheduler._assert_plan_binding", lambda *_args: None)
    hooks = provider._python_publication_join(value.request, value.plan, provider._inputs(require_unexpired=False))
    assert "python_handoff_after_execution" not in hooks
    assert hooks["python_handoff_after_native_execution"](run) is retained
    assert received == [run] and received[0] is run
    with pytest.raises(NativeRSISchedulerProviderError, match="supplier_replayed"):
        hooks["python_handoff_after_native_execution"](run)


def test_native_late_join_rejects_configured_supplier_drift_before_callback(tmp_path):
    value = _setup(tmp_path)
    provider = _configured_provider(value)
    provider.context.python_handoff_after_native_execution = _native_supplier_a
    provider.context.live_modules_sink = object()
    hooks = provider._python_publication_join(value.request, value.plan, provider._inputs(require_unexpired=False))
    provider.context.python_handoff_after_native_execution = _native_supplier_b
    with pytest.raises(NativeRSISchedulerProviderError, match="supplier_changed"):
        hooks["python_handoff_after_native_execution"](NativeTrustedProducerRun(object(), object(), object()))
