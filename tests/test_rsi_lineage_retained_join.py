"""Read-only lineage association cannot mint fresh execution or callbacks."""

from __future__ import annotations

import subprocess

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_multi_episode_policy import _controller
from test_rsi_producer_gateway import _fixture

from lunar_evolution.rsi_native_retained import (
    NativeRetainedEvidenceError,
    read_native_retained_candidate,
)
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerProviderError


@pytest.fixture(autouse=True)
def _no_process(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only association must never launch a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


def test_readonly_controller_binding_does_not_bind_fresh_dispatch(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    provider = value.gateway.config.receipt_provider
    plan = value.gateway._plan(value.request, value.memory)
    before = _inventory(value.root)
    provider.bind_python_admission_replay_controller(controller)
    provider.bind_python_admission_replay_controller(controller)
    assert provider._python_admission_replay_controller is controller
    assert provider._python_admission_controller is None
    assert controller._producer_publication_dispatch is None
    assert value.ledger.get_run(value.binding.run_id) is None
    assert provider._retained_lineage_options(value.request, value.memory, plan) == {}
    assert _inventory(value.root) == before


def test_readonly_controller_binding_cannot_be_replaced(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    replacement, _supplier = _controller(value, publication=True)
    provider = value.gateway.config.receipt_provider
    provider.bind_python_admission_replay_controller(controller)
    before = _inventory(value.root)
    with pytest.raises(NativeRSISchedulerProviderError, match="python_replay_controller_changed"):
        provider.bind_python_admission_replay_controller(replacement)
    assert provider._python_admission_replay_controller is controller
    assert provider._python_admission_controller is None
    assert _inventory(value.root) == before


@pytest.mark.parametrize("field,replacement", [
    ("producer_multi_episode_publication", False),
    ("producer_multi_episode_publication", 1),
    ("producer_child_execution", False),
    ("producer_workspace", None),
    ("ledger", object()),
])
def test_readonly_binding_refuses_component_or_mode_drift(tmp_path, monkeypatch, field, replacement):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    provider = value.gateway.config.receipt_provider
    plan = value.gateway._plan(value.request, value.memory)
    provider.bind_python_admission_replay_controller(controller)
    before = _inventory(value.root)
    setattr(controller, field, replacement)
    with pytest.raises(NativeRSISchedulerProviderError, match="python_replay_controller_invalid"):
        provider._retained_lineage_options(value.request, value.memory, plan)
    assert provider._python_admission_controller is None
    assert _inventory(value.root) == before


@pytest.mark.parametrize("inspection", [object(), lambda *args: None])
def test_foreign_inspection_refuses_before_workspace_or_native_recovery(tmp_path, monkeypatch, inspection):
    value = _fixture(tmp_path, monkeypatch)
    native = value.native
    before = _inventory(value.root)
    with pytest.raises(NativeRetainedEvidenceError, match="lineage_inspection_invalid"):
        read_native_retained_candidate(
            object(), candidate_id="candidate-1", expected_journal_sha256="1" * 64,
            expected_producer_execution_receipt_sha256="2" * 64,
            intent=native.intent, attestation=native.attestation, artifact=native.artifact,
            contract=native.contract, groups=native.groups,
            evaluator_kind=native.evaluator_kind, evaluator_fingerprint=native.evaluator_fingerprint,
            runner_fingerprint=native.runner_fingerprint, dependency_sha256=native.dependency_sha256,
            environment_sha256=native.environment_sha256, lineage_inspection=inspection,
        )
    assert _inventory(value.root) == before
