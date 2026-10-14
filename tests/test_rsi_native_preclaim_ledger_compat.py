"""Read-only legacy native ledger compatibility over inert, never-executed bytes."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from types import MappingProxyType

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture

from lunar_evolution.rsi_native_gateway import NativeRSIExecutionConfig, NativeRSISolverGateway
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)
from lunar_evolution.rsi_store import RSILedger


def _prepared(tmp_path, monkeypatch, *, bound=False):
    value = _fixture(tmp_path, monkeypatch)
    context = value.native if bound else replace(value.native, failure_ledger=None)
    provider = NativeRSISchedulerProvider(context)
    plan = provider.plan(value.request, value.memory)
    for name in ("run_native_trusted_producer", "run_native_trusted_producer_outcome"):
        monkeypatch.setattr(
            f"lunar_evolution.rsi_native_scheduler.{name}",
            lambda *_a, **_k: pytest.fail("preclaim launched inert native bytes"),
        )
    return value, provider, plan


def _callback(provider, callback):
    callback.rsi_fingerprint_config = lambda: {"fixture": "preclaim-ledger-compat-v1"}
    object.__setattr__(provider.context, "cancelled", callback)


def _assert_no_claims(value, plan, before):
    assert value.ledger.inspect_native_episode_claim(
        value.request, plan_sha256=plan.plan_sha256,
    ) is None
    assert value.ledger.get_episode(value.request.episode_id) is None
    assert value.ledger.episode_result(value.request.episode_id) is None
    assert _inventory(value.root) == before


def test_legacy_unbound_preclaim_uses_local_readonly_pin_without_rebinding(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    context = provider.context
    fingerprint = provider.rsi_fingerprint_config()
    before = _inventory(value.root)
    before_database = _inventory(tmp_path)["ledger.sqlite3"]
    observations = []
    connect = value.ledger._connect

    def readonly_connect():
        depth = getattr(value.ledger._observation_scope, "depth", 0)
        observations.append(depth)
        assert depth > 0
        return connect()

    monkeypatch.setattr(value.ledger, "_connect", readonly_connect)
    provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert observations == [1, 1]
    assert provider.context is context and context.failure_ledger is None
    assert provider._failure_ledger_identity is None
    assert provider.rsi_fingerprint_config() == fingerprint
    assert "failure_ledger" not in fingerprint
    monkeypatch.setattr(value.ledger, "_connect", connect)
    assert _inventory(tmp_path)["ledger.sqlite3"] == before_database
    _assert_no_claims(value, plan, before)


def test_gateway_hook_accepts_original_unbound_native_provider_without_effects(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(
        value.ledger, provider.plan, provider,
    ))
    before = _inventory(value.root)
    before_database = _inventory(tmp_path)["ledger.sqlite3"]
    fingerprint = gateway.rsi_fingerprint_config()
    gateway._validate_preclaim(value.request, plan)
    assert gateway.rsi_fingerprint_config() == fingerprint
    assert provider.context.failure_ledger is None
    assert provider._failure_ledger_identity is None
    assert _inventory(tmp_path)["ledger.sqlite3"] == before_database
    _assert_no_claims(value, plan, before)


@pytest.mark.parametrize("invalid", [None, True, "ledger", object()])
def test_unbound_preclaim_requires_exact_gateway_ledger_before_input_io(
    tmp_path, monkeypatch, invalid,
):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    monkeypatch.setattr(provider, "_inputs", lambda **_k: pytest.fail("invalid ledger read inputs"))
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_ledger_mismatch"):
        provider.validate_preclaim(value.request, plan, claim_ledger=invalid)
    _assert_no_claims(value, plan, before)


def test_unbound_preclaim_rejects_ledger_subclass_without_property_access(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)

    class ForeignLedger(RSILedger):
        @property
        def database(self):
            pytest.fail("invalid ledger property was evaluated")

    invalid = object.__new__(ForeignLedger)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_ledger_mismatch"):
        provider.validate_preclaim(value.request, plan, claim_ledger=invalid)
    _assert_no_claims(value, plan, before)


@pytest.mark.parametrize("same_database", [False, True])
def test_bound_preclaim_still_requires_exact_original_ledger_object(
    tmp_path, monkeypatch, same_database,
):
    value, provider, plan = _prepared(tmp_path, monkeypatch, bound=True)
    foreign = RSILedger(value.ledger.database if same_database else tmp_path / "foreign.sqlite3")
    before = _inventory(value.root)
    pin = provider._failure_ledger_identity
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_ledger_mismatch"):
        provider.validate_preclaim(value.request, plan, claim_ledger=foreign)
    assert provider.context.failure_ledger is value.ledger
    assert provider._failure_ledger_identity is pin
    _assert_no_claims(value, plan, before)


def test_bound_provider_cannot_drop_original_ledger_and_borrow_legacy_path(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch, bound=True)
    before = _inventory(value.root)
    pin = provider._failure_ledger_identity
    object.__setattr__(provider.context, "failure_ledger", None)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_context_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert provider._failure_ledger_identity is pin
    _assert_no_claims(value, plan, before)


def test_unbound_provider_cannot_install_failure_authority_after_construction(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    object.__setattr__(provider.context, "failure_ledger", value.ledger)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_context_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert provider._failure_ledger_identity is None
    _assert_no_claims(value, plan, before)


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("mutation", ["context", "failure_ledger", "constructor_pin"])
def test_preclaim_refuses_context_or_constructor_pin_changes_during_observation(
    tmp_path, monkeypatch, bound, boundary, mutation,
):
    value, provider, plan = _prepared(tmp_path, monkeypatch, bound=bound)
    foreign = RSILedger(tmp_path / "foreign.sqlite3")
    before = _inventory(value.root)
    calls = []

    def mutate():
        calls.append(None)
        if len(calls) == boundary:
            if mutation == "context":
                provider.context = replace(provider.context)
            elif mutation == "failure_ledger":
                object.__setattr__(provider.context, "failure_ledger", foreign)
            else:
                provider._failure_ledger_identity = MappingProxyType(
                    {} if provider._failure_ledger_identity is None
                    else dict(provider._failure_ledger_identity),
                )
        return False

    _callback(provider, mutate)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_context_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(calls) == boundary
    _assert_no_claims(value, plan, before)


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("boundary", [1, 2])
def test_preclaim_refuses_replaced_database_inode_without_pinning_the_replacement(
    tmp_path, monkeypatch, bound, boundary,
):
    value, provider, plan = _prepared(tmp_path, monkeypatch, bound=bound)
    foreign = RSILedger(tmp_path / "replacement.sqlite3")
    # SQLite initialization may still live in the WAL. Checkpoint fixture databases before
    # copying bytes, so post-refusal no-claim assertions inspect a complete replacement schema.
    for path in (value.ledger.database, foreign.database):
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            connection.close()
    before = _inventory(value.root)
    pin = provider._failure_ledger_identity
    database = value.ledger.database
    retained = tmp_path / "original-retained.sqlite3"
    calls = []

    def replace_database():
        calls.append(None)
        if len(calls) == boundary:
            database.rename(retained)
            database.write_bytes(foreign.database.read_bytes())
        return False

    _callback(provider, replace_database)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_ledger_changed"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert len(calls) == boundary
    assert provider._failure_ledger_identity is pin
    assert database.stat().st_ino != retained.stat().st_ino
    _assert_no_claims(value, plan, before)


def test_removed_unbound_database_is_not_recreated_by_claim_observation(tmp_path, monkeypatch):
    value, provider, plan = _prepared(tmp_path, monkeypatch)
    before = _inventory(value.root)
    database = value.ledger.database
    connect = value.ledger._connect

    def remove_before_connect():
        assert getattr(value.ledger._observation_scope, "depth", 0) > 0
        database.unlink()
        return connect()

    monkeypatch.setattr(value.ledger, "_connect", remove_before_connect)
    with pytest.raises(NativeRSISchedulerProviderError, match="preclaim_claim_invalid"):
        provider.validate_preclaim(value.request, plan, claim_ledger=value.ledger)
    assert not database.exists()
    assert provider.context.failure_ledger is None
    assert provider._failure_ledger_identity is None
    assert _inventory(value.root) == before
