from __future__ import annotations

from dataclasses import replace

import pytest
from test_rsi_native_gateway import bundle, make_request, plan_factory

from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_store import RSILedger


class PreclaimProvider:
    def __init__(self, ledger, action=None):
        self.ledger = ledger
        self.action = action
        self.version = 1
        self.events = []

    def rsi_fingerprint_config(self):
        return {"fixture": "preclaim-provider", "version": self.version}

    def validate_preclaim(self, request, plan, *, claim_ledger):
        assert claim_ledger is self.ledger
        assert claim_ledger.inspect_native_episode_claim(
            request, plan_sha256=plan.plan_sha256,
        ) is None
        self.events.append("preclaim")
        if self.action is not None:
            self.action(request, plan)

    def __call__(self, request, plan):
        assert self.ledger.inspect_native_episode_claim(
            request, plan_sha256=plan.plan_sha256,
        ).status == "started"
        self.events.append("provider")
        return bundle(request, plan)


def configured(tmp_path, action=None):
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    provider = PreclaimProvider(ledger, action)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    return request, ledger, provider, gateway


def assert_unclaimed(ledger, request):
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    assert ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) is None
    assert ledger.episode_result(request.episode_id) is None


def test_fresh_claim_validates_before_provider_and_replay_skips_hook(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    result = gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert result.status == "completed"
    assert provider.events == ["preclaim", "provider"]
    # Even an unavailable fresh gate cannot interfere with terminal replay.
    provider.validate_preclaim = False
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT) == result
    assert provider.events == ["preclaim", "provider"]
    assert ledger.episode_result(request.episode_id)[1] == result


def test_existing_started_claim_refuses_without_preclaim(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    provider.validate_preclaim = False
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == []


def test_hook_failure_leaves_no_claim_and_no_provider_call(tmp_path):
    def refuse(*_):
        raise RuntimeError("fixture cancellation or deadline refusal")

    request, ledger, provider, gateway = configured(tmp_path, refuse)
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_failed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ["preclaim"]
    assert_unclaimed(ledger, request)


@pytest.mark.parametrize("invalid", [False, "invalid", 1])
def test_present_invalid_hook_cannot_bypass_gate(tmp_path, invalid):
    request, ledger, provider, gateway = configured(tmp_path)
    provider.validate_preclaim = invalid
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_hook_invalid"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == []
    assert_unclaimed(ledger, request)


def test_hook_configuration_drift_refuses_before_claim(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    provider.action = lambda *_: setattr(provider, "version", 2)
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_configuration_changed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ["preclaim"]
    assert_unclaimed(ledger, request)


def test_hook_replacement_refuses_even_with_same_provider_fingerprint(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    provider.action = lambda *_: setattr(provider, "validate_preclaim", lambda *a, **kw: None)
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_configuration_changed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ["preclaim"]
    assert_unclaimed(ledger, request)


def test_execution_configuration_replacement_refuses(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    provider.action = lambda *_: setattr(gateway, "config", replace(gateway.config))
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_configuration_changed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ["preclaim"]
    assert_unclaimed(ledger, request)


def test_preclaim_ledger_write_is_refused_and_observation_scope_restored(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    provider.action = lambda req, plan: ledger.claim_native_episode(req, plan_sha256=plan.plan_sha256)
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_failed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert_unclaimed(ledger, request)
    assert provider.events == ["preclaim"]
    provider.action = None
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT).status == "completed"
    assert provider.events == ["preclaim", "preclaim", "provider"]


def test_hook_descriptor_cannot_write_during_hook_resolution(tmp_path):
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")

    class DescriptorProvider:
        @property
        def validate_preclaim(self):
            ledger.claim_native_episode(
                request, plan_sha256=plan_factory(request, EMPTY_MEMORY_SNAPSHOT).plan_sha256,
            )

        def __call__(self, *args):
            pytest.fail("provider must not execute")

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, DescriptorProvider()))
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_failed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert_unclaimed(ledger, request)


@pytest.mark.parametrize("replace_on_read", [1, 2])
def test_descriptor_configuration_replacement_cannot_bypass_gate(tmp_path, replace_on_read):
    request = make_request()
    ledger = RSILedger(tmp_path / "ledger.sqlite")

    class DescriptorProvider(PreclaimProvider):
        hook_reads = 0

        @property
        def validate_preclaim(self):
            self.hook_reads += 1
            if self.hook_reads == replace_on_read:
                gateway.config = replace(gateway.config)
                if replace_on_read == 1:
                    return None
            return self._gate

        def _gate(self, req, plan, *, claim_ledger):
            return super().validate_preclaim(req, plan, claim_ledger=claim_ledger)

    provider = DescriptorProvider(ledger)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))
    with pytest.raises(NativeRSISolverGatewayError, match="preclaim_configuration_changed"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ([] if replace_on_read == 1 else ["preclaim"])
    assert_unclaimed(ledger, request)


def test_competing_started_claim_after_hook_is_not_reexecuted(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    external = RSILedger(ledger.database)
    provider.action = lambda req, plan: external.claim_native_episode(req, plan_sha256=plan.plan_sha256)
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    assert provider.events == ["preclaim"]
    assert ledger.inspect_native_episode_claim(
        request, plan_sha256=plan_factory(request, EMPTY_MEMORY_SNAPSHOT).plan_sha256,
    ).status == "started"


def test_competing_terminal_claim_after_hook_grants_replay_only(tmp_path):
    request, ledger, provider, gateway = configured(tmp_path)
    external = RSILedger(ledger.database)
    winner = NativeRSISolverGateway(NativeRSIExecutionConfig(external, plan_factory, bundle))
    results = []
    provider.action = lambda req, plan: results.append(winner.run(req, EMPTY_MEMORY_SNAPSHOT))
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT) == results[0]
    assert provider.events == ["preclaim"]


def test_provider_without_hook_keeps_original_injected_protocol(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, bundle))
    assert gateway.run(make_request(), EMPTY_MEMORY_SNAPSHOT).status == "completed"


def test_explicit_none_hook_keeps_original_injected_protocol(tmp_path):
    request, _, provider, gateway = configured(tmp_path)
    provider.validate_preclaim = None
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT).status == "completed"
    assert provider.events == ["provider"]
