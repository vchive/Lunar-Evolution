"""Explicit native scheduler bridge at the producer prepared boundary."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_rsi_python_admission import _setup

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_native_candidate import select_native_candidate
from lunar_evolution.rsi_native_inputs import NativeRSIInputDescriptor
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _provider(value):
    value.plan = replace(
        value.plan,
        candidate_selector_sha256=component_fingerprint(select_native_candidate),
        plan_sha256=None,
    )
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    artifact = type("Artifact", (), {
        "descriptor": type("Descriptor", (), {"digest": lambda _self: "a" * 64})(),
        "artifact_sha256": "a" * 64,
    })()
    contract = type("Contract", (), {"digest": lambda _self: value.request.contract_sha256})()
    provider.context = type("Context", (), {
        "workspace": value.workspace,
        "intent": value.binding.intent,
        "attestation": value.binding.attestation,
        "artifact": artifact,
        "contract": contract,
        "evaluator_kind": value.journal.evaluator_kind,
        "evaluator_fingerprint": value.request.evaluator_sha256,
        "runner_fingerprint": value.journal.runner_fingerprint,
        "dependency_sha256": value.journal.dependency_sha256,
        "environment_sha256": value.request.environment_sha256,
    })()
    input_descriptor = NativeRSIInputDescriptor(
        workspace=value.workspace,
        journal_id=value.binding.intent.journal_id,
        inputs_path=value.workspace / "evolution" / "producer-batches" / value.binding.intent.journal_id / ".rsi-input",
        request_sha256=value.request.digest(),
        memory_snapshot_sha256=value.controller.snapshot.digest(),
        manifest_sha256="a" * 64,
        request_json=canonical_json(value.request.to_dict()),
        memory_json=value.controller.snapshot.to_bytes(),
        manifest_json=b"{}",
        deadline_unix=value.binding.deadline_unix,
    )
    provider._inputs = lambda *, require_unexpired: input_descriptor
    provider._python_admission_controller = value.controller
    return provider


def test_explicit_prepared_boundary_bridge_joins_original_handoff_and_anchor(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _provider(value)
    seen = []

    class Bridge:
        def __init__(self, owner, descriptor, *, wait_check):
            seen.append((owner, descriptor, wait_check))

        def pin_live(self, descriptor):
            assert descriptor is seen[0][1]
            return "f" * 64

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.PythonAdmissionBridgeAdapter", Bridge,
    )

    def prepared_observer(journal):
        return provider.pin_python_admission_at_prepared_boundary(
            value.request,
            value.plan,
            prepared_journal=journal,
            python_handoff_sha256=value.handoff.handoff_sha256,
            python_handoff_file_pin=value.pin,
            expected_anchor_sha256=value.anchor.anchor_sha256,
        )

    result = prepared_observer(value.journal)

    assert result == "f" * 64
    assert len(seen) == 1
    assert seen[0][0] is value.controller
    assert seen[0][1].run_id == value.plan.run_id
    assert seen[0][1].episode_id == value.request.episode_id
    assert callable(seen[0][2])


@pytest.mark.parametrize("field", ["python_handoff_sha256", "expected_anchor_sha256"])
def test_explicit_prepared_boundary_refuses_digest_drift_before_bridge(tmp_path, monkeypatch, field):
    value = _setup(tmp_path)
    provider = _provider(value)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.PythonAdmissionBridgeAdapter",
        lambda *_args, **_kwargs: pytest.fail("digest drift reached bridge"),
    )
    kwargs = {
        "prepared_journal": value.journal,
        "python_handoff_sha256": value.handoff.handoff_sha256,
        "python_handoff_file_pin": value.pin,
        "expected_anchor_sha256": value.anchor.anchor_sha256,
    }
    kwargs[field] = "e" * 64
    with pytest.raises(NativeRSISchedulerProviderError):
        provider.pin_python_admission_at_prepared_boundary(
            value.request, value.plan, **kwargs,
        )


def test_explicit_prepared_boundary_refuses_controller_workspace_drift(tmp_path):
    value = _setup(tmp_path)
    provider = _provider(value)
    provider._python_admission_controller.producer_workspace = tmp_path / "foreign"
    with pytest.raises(NativeRSISchedulerProviderError, match="workspace_mismatch"):
        provider.pin_python_admission_at_prepared_boundary(
            value.request,
            value.plan,
            prepared_journal=value.journal,
            python_handoff_sha256=value.handoff.handoff_sha256,
            python_handoff_file_pin=value.pin,
            expected_anchor_sha256=value.anchor.anchor_sha256,
        )


def test_explicit_prepared_boundary_rechecks_anchor_after_bridge_returns(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _provider(value)
    anchor_path = value.batch / "python-producer-admission-anchor.json"

    class Bridge:
        def __init__(self, _owner, _descriptor, *, wait_check):
            assert callable(wait_check)

        def pin_live(self, _descriptor):
            anchor_path.write_bytes(anchor_path.read_bytes() + b"drift")
            return "f" * 64

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.PythonAdmissionBridgeAdapter", Bridge,
    )

    with pytest.raises(NativeRSISchedulerProviderError):
        provider.pin_python_admission_at_prepared_boundary(
            value.request,
            value.plan,
            prepared_journal=value.journal,
            python_handoff_sha256=value.handoff.handoff_sha256,
            python_handoff_file_pin=value.pin,
            expected_anchor_sha256=value.anchor.anchor_sha256,
        )


def test_explicit_prepared_boundary_rejects_request_drift_before_journal_read(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    provider = _provider(value)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.parse_producer_bundle_publication_journal",
        lambda *_args, **_kwargs: pytest.fail("request drift reached journal"),
    )
    with pytest.raises(NativeRSISchedulerProviderError, match="request_input_mismatch"):
        provider.pin_python_admission_at_prepared_boundary(
            replace(value.request, solver_id="other-solver"),
            value.plan,
            prepared_journal=value.journal,
            python_handoff_sha256=value.handoff.handoff_sha256,
            python_handoff_file_pin=value.pin,
            expected_anchor_sha256=value.anchor.anchor_sha256,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("launch_id", "foreign-launch"), ("manifest_sha256", "b" * 64), ("deadline_unix", 42.0)],
)
def test_explicit_prepared_boundary_rejects_plan_authority_drift_before_journal_read(
    tmp_path, monkeypatch, field, value,
):
    fixture = _setup(tmp_path)
    provider = _provider(fixture)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.parse_producer_bundle_publication_journal",
        lambda *_args, **_kwargs: pytest.fail("plan drift reached journal"),
    )
    plan = replace(fixture.plan, **{field: value}, plan_sha256=None)
    with pytest.raises(NativeRSISchedulerProviderError, match="plan_.*mismatch"):
        provider.pin_python_admission_at_prepared_boundary(
            fixture.request,
            plan,
            prepared_journal=fixture.journal,
            python_handoff_sha256=fixture.handoff.handoff_sha256,
            python_handoff_file_pin=fixture.pin,
            expected_anchor_sha256=fixture.anchor.anchor_sha256,
        )

def test_normal_native_dispatch_keeps_python_admission_hook_explicit(tmp_path, monkeypatch):
    """Binding a controller never upgrades ordinary native dispatch to Python admission."""
    value = _setup(tmp_path)
    provider = _provider(value)
    # The focused provider fixture only needs enough inert fields to reach the patched
    # scheduler call.  No producer, broker, evaluator or filesystem launch is allowed.
    provider.context = SimpleNamespace(
        workspace=value.workspace, producer_root=value.workspace,
        intent=provider.context.intent, attestation=provider.context.attestation,
        artifact=provider.context.artifact, contract=provider.context.contract,
        broker_config=object(), groups=(), evaluator_kind=value.journal.evaluator_kind,
        evaluator_fingerprint=value.request.evaluator_sha256,
        runner_fingerprint=value.journal.runner_fingerprint,
        dependency_sha256=value.journal.dependency_sha256,
        environment_sha256=value.request.environment_sha256, strategy=object(),
        execution_control=None, cancelled=None, failure_ledger=None,
    )
    bridge_calls = []
    monkeypatch.setattr(
        provider, "_pin_python_admission_before_dispatch",
        lambda *_args, **_kwargs: bridge_calls.append("unexpected"),
    )
    scheduler_calls = []

    def stop_before_launch(*_args, **_kwargs):
        scheduler_calls.append("native")
        raise RuntimeError("inert scheduler stop")

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer",
        stop_before_launch,
    )
    with pytest.raises(NativeRSISchedulerProviderError, match="attempt_failed"):
        provider(value.request, value.plan)
    assert scheduler_calls == ["native"]
    assert bridge_calls == []
