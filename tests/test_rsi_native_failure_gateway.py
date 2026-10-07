"""Actual inert native failures through durable gateway publication and read-only restore."""
from __future__ import annotations

import shutil
from dataclasses import replace

import pytest
from test_rsi_native_failure_provenance import _native_failure_rsi_fixture

import lunar_evolution.rsi_native_scheduler as scheduler
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_failure import read_native_rsi_failure_provenance
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_native_scheduler import make_native_rsi_scheduler_provider
from lunar_evolution.rsi_store import RSILedger


class FixtureCrash(BaseException):
    pass


def _gateway(prepared):
    return NativeRSISolverGateway(NativeRSIExecutionConfig(
        prepared.ledger, prepared.provider.plan, prepared.provider,
    ))


def _pins(prepared):
    evidence = read_native_rsi_failure_provenance(prepared.batch)
    return {"expected_claim_sha256": evidence.claim_sha256,
            "expected_provenance_sha256": evidence.provenance_sha256}


def _interrupt_publication(prepared, monkeypatch):
    gateway = _gateway(prepared)
    def crash(*_a, **_k):
        raise FixtureCrash("provenance persisted before result")
    with monkeypatch.context() as patch:
        patch.setattr(prepared.ledger, "publish_native_episode_result", crash)
        with pytest.raises(FixtureCrash):
            gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None
    return gateway


def test_actual_nonzero_gateway_registers_failure_and_restart_rereads_original_proof(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _gateway(prepared)
    for name in ("_build_receipts", "_read_retained", "select_native_candidate"):
        monkeypatch.setattr(scheduler, name, lambda *_a, **_k: pytest.fail("failure entered success pipeline"))
    result = gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
    assert result.status == "failed" and dict(result.solver_provenance)["native_exit_code"] == 7
    assert result.candidate_receipt_sha256 is None and result.solver_score is None
    assert not (prepared.batch / "native-rsi.provenance.json").exists()
    retained = {p: (p.read_bytes(), p.stat().st_ino) for p in prepared.workspace.rglob("*") if p.is_file()}
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("replayed launch"))
    ledger = RSILedger(prepared.ledger.database)
    provider = make_native_rsi_scheduler_provider(replace(prepared.context, failure_ledger=ledger))
    restarted = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, provider.plan, provider))
    assert restarted.run(prepared.request, EMPTY_MEMORY_SNAPSHOT) == result
    assert restarted.validate_replay(prepared.request, EMPTY_MEMORY_SNAPSHOT, result) == result
    assert retained == {p: (p.read_bytes(), p.stat().st_ino) for p in prepared.workspace.rglob("*") if p.is_file()}


def test_provenance_before_result_crash_requires_explicit_restore_without_launch(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _interrupt_publication(prepared, monkeypatch)
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("restore launched"))
    pins = _pins(prepared)
    inspected = gateway.inspect_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **pins)
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None
    result = gateway.restore_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **pins)
    assert result == inspected and result.status == "failed"
    assert gateway.restore_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **pins) == result
    assert prepared.ledger.episode_result(prepared.request.episode_id) == (prepared.request, result)


@pytest.mark.parametrize("pin", ["expected_claim_sha256", "expected_provenance_sha256"])
def test_restore_wrong_independent_pin_refuses_before_result_registration(tmp_path, monkeypatch, pin):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _interrupt_publication(prepared, monkeypatch)
    pins = {**_pins(prepared), pin: "0" * 64}
    with pytest.raises(NativeRSISolverGatewayError):
        gateway.restore_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **pins)
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None


def test_restore_cannot_overwrite_immutable_unknown_result(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _interrupt_publication(prepared, monkeypatch)
    request = prepared.request
    unknown = SolverResult(request.episode_id, request.digest(), "unknown", None, None, None, "a" * 64)
    prepared.ledger.publish_native_episode_result(request, plan_sha256=prepared.plan.plan_sha256, result=unknown)
    with pytest.raises(NativeRSISolverGatewayError, match="failure_claim_mismatch"):
        gateway.restore_failure(request, EMPTY_MEMORY_SNAPSHOT, **_pins(prepared))
    assert prepared.ledger.episode_result(request.episode_id) == (request, unknown)


def test_failed_replay_without_evidence_reader_cannot_trust_saved_database(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _gateway(prepared)
    gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
    monkeypatch.setattr(prepared.provider, "recover", None)
    with pytest.raises(NativeRSISolverGatewayError, match="failure_reader_required"):
        gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)


def test_prepared_gateway_refuses_same_content_database_inode_replacement_before_connect(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _interrupt_publication(prepared, monkeypatch)
    database = prepared.ledger.database
    replacement = database.with_name("replacement.sqlite")
    shutil.copyfile(database, replacement)
    replacement.replace(database)
    monkeypatch.setattr(prepared.ledger, "_connect", lambda: pytest.fail("opened substituted database"))
    with pytest.raises(NativeRSISolverGatewayError, match="ledger_changed"):
        gateway.restore_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **_pins(prepared))


def test_live_provider_cannot_replace_original_claim_creation_timestamp(tmp_path, monkeypatch):
    import sqlite3
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _gateway(prepared)
    invoke = type(prepared.provider).__call__
    def replace_claim(provider, request, plan):
        with sqlite3.connect(prepared.ledger.database) as connection:
            connection.execute("UPDATE rsi_native_episode_claims SET created_at = ? WHERE episode_id = ?",
                               ("changed-original-claim", request.episode_id))
        return invoke(provider, request, plan)
    monkeypatch.setattr(type(prepared.provider), "__call__", replace_claim)
    with pytest.raises(NativeRSISolverGatewayError, match="failure_claim_mismatch"):
        gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None


@pytest.mark.parametrize("operation", ["live", "restore"])
def test_transaction_rechecks_original_full_claim_before_result_write(tmp_path, monkeypatch, operation):
    import sqlite3

    from lunar_evolution.rsi_learning import RSILearningError
    prepared = _native_failure_rsi_fixture(tmp_path)
    gateway = _gateway(prepared) if operation == "live" else _interrupt_publication(prepared, monkeypatch)
    publish = prepared.ledger.publish_native_episode_result
    def replace_claim(*args, **kwargs):
        with sqlite3.connect(prepared.ledger.database) as connection:
            connection.execute("UPDATE rsi_native_episode_claims SET created_at = ? WHERE episode_id = ?",
                               ("changed-before-transaction", prepared.request.episode_id))
        return publish(*args, **kwargs)
    monkeypatch.setattr(prepared.ledger, "publish_native_episode_result", replace_claim)
    with pytest.raises((NativeRSISolverGatewayError, RSILearningError)) as error:
        if operation == "live":
            gateway.run(prepared.request, EMPTY_MEMORY_SNAPSHOT)
        else:
            gateway.restore_failure(prepared.request, EMPTY_MEMORY_SNAPSHOT, **_pins(prepared))
    assert "claim_identity_drift" in str(error.value) or "claim_identity_drift" in str(error.value.__cause__)
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None
