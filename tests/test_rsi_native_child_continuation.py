"""A retained claim never grants a fresh physical invocation after its stack ends."""

from concurrent.futures import ThreadPoolExecutor
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


def _setup(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    request = make_request()
    calls = []

    def provider(req, plan):
        calls.append(req.digest())
        return bundle(req, plan)

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, plan_factory, provider))

    def acquire(plan):
        return ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)

    return gateway, request, acquire, calls


def test_fresh_child_continuation_maps_publishes_once_and_then_replays(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        result = dispatch(request)
        assert result.status == "completed"
        with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
            dispatch(request)
    assert calls == [request.digest()]
    assert gateway.run(request, EMPTY_MEMORY_SNAPSHOT) == result
    assert calls == [request.digest()]


def test_unused_continuation_expires_and_retained_claim_refuses_relaunch(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        pass
    with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
        dispatch(request)
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        gateway.run(request, EMPTY_MEMORY_SNAPSHOT)
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"), gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ):
        pytest.fail("retained started claim reminted a continuation")
    assert calls == []
    assert gateway.ledger.episode_result(request.episode_id) is None


def test_child_continuation_cannot_move_to_another_thread(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(
            NativeRSISolverGatewayError, match="continuation_unavailable",
        ):
            pool.submit(dispatch, request).result(timeout=5)
        # A wrong-thread attempt grants nothing; only the original owner may use its slot.
        assert dispatch(request).status == "completed"
    assert calls == [request.digest()]


def test_child_owner_refusal_after_claim_preserves_started_without_provider(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    live = True

    def check():
        if not live:
            raise RuntimeError("owner no longer active")

    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=check,
    ) as dispatch:
        live = False
        with pytest.raises(RuntimeError, match="owner no longer active"):
            dispatch(request)
        live = True
        with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
            dispatch(request)
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    assert gateway.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256).status == "started"
    assert calls == []


def test_changed_request_consumes_slot_without_invoking_provider(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        with pytest.raises(NativeRSISolverGatewayError, match="configuration_changed"):
            dispatch(replace(request, episode_id="other"))
        with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
            dispatch(request)
    assert calls == []


def test_equal_configuration_replacement_cannot_continue_an_acquired_child(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    original = gateway.config
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        gateway.config = replace(original)
        assert gateway.config == original and gateway.config is not original
        with pytest.raises(NativeRSISolverGatewayError, match="configuration_changed"):
            dispatch(request)
        gateway.config = original
        with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
            dispatch(request)
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    assert gateway.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256).status == "started"
    assert calls == [] and gateway.ledger.episode_result(request.episode_id) is None


def test_launch_change_between_claim_and_dispatch_preserves_original_claim(tmp_path):
    gateway, request, acquire, calls = _setup(tmp_path)
    launch = "launch"

    def changing_plan(req, memory):
        return replace(plan_factory(req, memory), launch_id=launch, plan_sha256=None)

    gateway.config = replace(gateway.config, plan_factory=changing_plan)
    original = changing_plan(request, EMPTY_MEMORY_SNAPSHOT)
    with gateway._fresh_child_dispatch(
        request, EMPTY_MEMORY_SNAPSHOT, claim_factory=acquire, check_owner=lambda: None,
    ) as dispatch:
        launch = "different-launch"
        with pytest.raises(NativeRSISolverGatewayError, match="plan_changed"):
            dispatch(request)
        launch = "launch"
        with pytest.raises(NativeRSISolverGatewayError, match="continuation_unavailable"):
            dispatch(request)
    assert gateway.ledger.inspect_native_episode_claim(request, plan_sha256=original.plan_sha256).status == "started"
    assert calls == [] and gateway.ledger.episode_result(request.episode_id) is None
