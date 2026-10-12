"""Explicit native scheduler bridge at the producer prepared boundary."""

from __future__ import annotations

import pytest
from test_rsi_python_admission import _setup

from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)


def _provider(value):
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider.context = type("Context", (), {
        "workspace": value.workspace,
        "intent": value.binding.intent,
        "evaluator_kind": value.journal.evaluator_kind,
        "runner_fingerprint": value.journal.runner_fingerprint,
        "dependency_sha256": value.journal.dependency_sha256,
    })()
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
