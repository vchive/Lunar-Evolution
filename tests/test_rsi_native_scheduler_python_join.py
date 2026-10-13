"""Opt-in provider wiring keeps late evidence behind native execution."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_scheduler import _context
from test_rsi_native_scheduler_prepared_boundary import _provider
from test_rsi_python_admission import _setup

from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProviderError,
)


def _supplier_a(_receipt, _output):
    raise AssertionError("inert supplier must not run before native dispatch")


def _supplier_b(_receipt, _output):
    raise AssertionError("a different inert supplier must not run before dispatch")


def _strategy_fixture():
    return None


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
