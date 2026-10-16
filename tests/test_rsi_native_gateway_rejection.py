"""Facade-only rejection gates over real SQLite/P files and inert authority seams.

These cases test mapping, original claims and repeated reads. Inspector/native
authority is mocked explicitly; these are not C1/C2 controller acceptance.
"""

from __future__ import annotations

import shutil
import socket
import sqlite3
import subprocess
from dataclasses import replace

import pytest
from test_rsi_native_rejection import polluted_evidence
from test_rsi_native_scheduler_rejection import native_seams, provider_fixture

from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionError,
    NativeRSIRejectionFilePin,
    map_native_rejection_to_solver_result,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerProvider
from lunar_evolution.rsi_publication_lineage import StartedRSIRejectionInspection


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("gateway unit fixture attempted execution or network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _fixture(tmp_path, monkeypatch):
    value = provider_fixture(tmp_path, monkeypatch)
    native_seams(value, monkeypatch)
    _, pin = persist_native_rsi_rejection_provenance(value.batch, value.evidence, retained_bytes=0)
    value.pin = pin
    value.evidence = read_native_rsi_rejection_provenance(value.batch, expected_file_pin=pin)
    value.gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
        value.ledger, lambda *_args: value.plan, value.provider,
    ))
    return value


def _pins(value):
    return {"expected_checkpoint_sha256": "a" * 64, "expected_episode_record_sha256": "b" * 64,
            "expected_claim_sha256": value.evidence.claim_sha256, "expected_provenance_file_pin": value.pin}


def _read_seam(value, monkeypatch):
    calls = []

    def inspection_init(self, controller, **kwargs):
        # Explicit unit seam; no simulated checkpoint is accepted as C2 truth.
        calls.append(("inspector", controller, kwargs))
        assert kwargs["request"] == value.request
        assert kwargs["memory"] == EMPTY_MEMORY_SNAPSHOT
        assert kwargs["native_plan"] == value.plan
        assert {k: kwargs[k] for k in _pins(value)} == _pins(value)

    def recover(provider, request, plan, *, inspection):
        assert provider is value.provider and type(inspection) is StartedRSIRejectionInspection
        assert request == value.request and plan == value.plan
        calls.append(("read",))
        return read_native_rsi_rejection_provenance(value.batch, expected_file_pin=value.pin)

    monkeypatch.setattr(StartedRSIRejectionInspection, "__init__", inspection_init)
    monkeypatch.setattr(NativeRSISchedulerProvider, "recover_rejection", recover)
    monkeypatch.setattr(value.provider, "recover", lambda *_: pytest.fail("started read used terminal replay"))
    return calls


def test_pure_mapping_precedes_ledger_for_nested_callback_pollution(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    callbacks = []
    evidence = polluted_evidence("request-extra-method", callbacks)
    monkeypatch.setattr(value.gateway, "_assert_ledger", lambda: pytest.fail("bad shape reached ledger"))
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        value.gateway._map_outcome(evidence.plan.request, evidence.plan, evidence)
    assert callbacks == []


def test_mapping_requires_original_ledger_and_complete_original_claim(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    mapped = value.gateway._map_outcome(value.request, value.plan, value.evidence,
                                        expected_claim=value.evidence.claim)
    assert mapped.status == "failed" and mapped.terminal_reason == "native_all_rejected"
    assert mapped.solver_score is None and mapped.official_evaluation_receipt_sha256 is None
    assert value.ledger.episode_result(value.request.episode_id) is None
    changed = replace(value.evidence.claim, created_at="different-original")
    with pytest.raises(NativeRSISolverGatewayError, match="rejection_claim_mismatch"):
        value.gateway._map_outcome(value.request, value.plan, value.evidence, expected_claim=changed)
    with pytest.raises(NativeRSIRejectionError, match="provenance_pin_mismatch"):
        replace(value.evidence, ledger_identity={**dict(value.evidence.ledger_identity), "inode": 999999})


@pytest.mark.parametrize("field", ["expected_checkpoint_sha256", "expected_episode_record_sha256",
                                 "expected_claim_sha256", "expected_provenance_file_pin"])
def test_invalid_pins_refuse_before_plan_or_provider(tmp_path, monkeypatch, field):
    value = _fixture(tmp_path, monkeypatch)
    pins = {**_pins(value), field: None}
    monkeypatch.setattr(value.gateway, "_plan", lambda *_: pytest.fail("invalid pin reached plan"))
    with pytest.raises(NativeRSISolverGatewayError, match="rejection_pin_invalid"):
        value.gateway.inspect_rejection(value.request, EMPTY_MEMORY_SNAPSHOT, **pins)


def test_started_inspection_repeats_original_p_without_result_write(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    calls = _read_seam(value, monkeypatch)
    before = (value.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).stat()
    observed = value.gateway.inspect_rejection(value.request, EMPTY_MEMORY_SNAPSHOT, **_pins(value))
    assert observed == map_native_rejection_to_solver_result(value.request, value.plan, value.evidence)
    assert [c[0] for c in calls] == ["inspector", "read", "read"]
    assert value.ledger.episode_result(value.request.episode_id) is None
    assert (value.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).stat() == before


def test_provider_replacement_during_plan_is_rejected_before_claim_read(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    original = value.gateway.config

    def drift(*_args):
        value.gateway.config = replace(original)
        return value.plan

    monkeypatch.setattr(value.gateway, "_plan", drift)
    monkeypatch.setattr(value.ledger, "inspect_native_episode_claim", lambda *_a, **_k: pytest.fail("drift reached claim"))
    with pytest.raises(NativeRSISolverGatewayError, match="rejection_configuration_changed"):
        value.gateway.inspect_rejection(value.request, EMPTY_MEMORY_SNAPSHOT, **_pins(value))


def test_restore_guard_cannot_replace_p_and_register_failed_result(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    _read_seam(value, monkeypatch)
    path = value.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME

    def replace_p():
        path.rename(value.batch / "retained-original-P")
        path.write_bytes((value.batch / "retained-original-P").read_bytes())
        path.chmod(0o400)

    with pytest.raises(NativeRSIRejectionError):
        value.gateway.restore_rejection(value.request, EMPTY_MEMORY_SNAPSHOT,
                                        before_publish=replace_p, **_pins(value))
    assert value.ledger.episode_result(value.request.episode_id) is None
    assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"


def test_same_bytes_database_replacement_refuses_before_connect(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    original = value.ledger.database
    replacement = tmp_path / "replacement.sqlite3"
    shutil.copyfile(original, replacement)
    replacement.replace(original)
    monkeypatch.setattr(value.ledger, "_connect", lambda: pytest.fail("replacement opened"))
    with pytest.raises(NativeRSISolverGatewayError, match="ledger_changed"):
        value.gateway.inspect_rejection(value.request, EMPTY_MEMORY_SNAPSHOT, **_pins(value))


def test_fresh_route_uses_live_reader_and_original_expected_claim(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(NativeRSISchedulerProvider, "__call__", lambda *_: value.evidence)
    monkeypatch.setattr(NativeRSISchedulerProvider, "recover_live_rejection", lambda *_: (
        calls.append("live") or read_native_rsi_rejection_provenance(value.batch, expected_file_pin=value.pin)
    ))
    monkeypatch.setattr(value.provider, "recover", lambda *_: pytest.fail("fresh route used historical reader"))
    result = value.gateway._execute_acquired_claim(value.request, value.plan, value.evidence.claim)
    assert calls == ["live"] and result.status == "failed"
    assert value.ledger.episode_result(value.request.episode_id) == (value.request, result)
    claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
    assert replace(claim, status="started") == value.evidence.claim


@pytest.mark.parametrize("drift", ["configuration", "claim"])
def test_fresh_repeat_drift_cannot_register_result(tmp_path, monkeypatch, drift):
    value = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(NativeRSISchedulerProvider, "__call__", lambda *_: value.evidence)

    def recover(*_args):
        if drift == "configuration":
            value.gateway.config = replace(value.gateway.config)
        else:
            with sqlite3.connect(value.ledger.database) as connection:
                connection.execute("UPDATE rsi_native_episode_claims SET created_at = ? WHERE episode_id = ?",
                                   ("changed-original", value.request.episode_id))
        return value.evidence

    monkeypatch.setattr(NativeRSISchedulerProvider, "recover_live_rejection", recover)
    with pytest.raises(NativeRSISolverGatewayError, match="rejection_configuration_changed|rejection_claim_mismatch"):
        value.gateway._execute_acquired_claim(value.request, value.plan, value.evidence.claim)
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_strict_pin_type_does_not_accept_subclasses():
    class Foreign(NativeRSIRejectionFilePin):
        pass

    with pytest.raises(NativeRSIRejectionError):
        Foreign(NATIVE_RSI_REJECTION_PROVENANCE_NAME, "c" * 64, 10, 1, 2, 1, 3)


@pytest.mark.parametrize("kind", ["callback", "subclass"])
@pytest.mark.parametrize("route", ["map", "inspect", "fresh"])
def test_other_provider_cannot_use_parsed_p_as_rejection_authority(tmp_path, monkeypatch, kind, route):
    value = _fixture(tmp_path, monkeypatch)
    callbacks = []

    class Callback:
        def __call__(self, *_args):
            return value.evidence

        @property
        def recover(self):
            callbacks.append("recover")
            raise AssertionError("foreign property invoked")

        @property
        def assert_failure_ledger(self):
            callbacks.append("ledger")
            raise AssertionError("foreign property invoked")

    class Subclass(NativeRSISchedulerProvider):
        def __call__(self, *_args):
            return value.evidence

    provider = Callback() if kind == "callback" else Subclass.__new__(Subclass)
    value.gateway.config = replace(value.gateway.config, receipt_provider=provider)
    if route == "map":
        operation = lambda: value.gateway._map_outcome(value.request, value.plan, value.evidence)
    elif route == "inspect":
        operation = lambda: value.gateway.inspect_rejection(value.request, EMPTY_MEMORY_SNAPSHOT, **_pins(value))
    else:
        operation = lambda: value.gateway._execute_acquired_claim(value.request, value.plan, value.evidence.claim)
    with pytest.raises(NativeRSISolverGatewayError, match="rejection_reader_required"):
        operation()
    assert callbacks == []
    assert value.ledger.episode_result(value.request.episode_id) is None
