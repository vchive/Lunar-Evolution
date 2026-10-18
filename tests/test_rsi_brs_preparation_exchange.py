"""Inert exact-DTO transport tests; natural provider integration is a separate gate."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import test_rsi_python_brs_publication_inputs as input_fixture

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_preparation_exchange import _BRSNativePreparationExchange
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    _BRSWorkerTerminalEndpoint,
    _PrimitiveExchange,
)
from lunar_evolution.rsi_store import NativeEpisodeClaim, RSILedger

prepared = input_fixture.prepared


def _claim(value):
    request, plan = value.plan.request, value.plan
    return NativeEpisodeClaim(request.episode_id, request.digest(), plan.plan_sha256, "started",
                              RSILedger._native_claim_digest(request.episode_id, request.digest(), plan.plan_sha256),
                              "2026-10-18T00:00:00Z")


def _exchange(value, *, deadline=None):
    return _BRSNativePreparationExchange(value.plan.request, expected_plan_sha256=value.plan.plan_sha256,
                                        deadline=time.monotonic() + 5 if deadline is None else deadline)


def _submit(pool, exchange, value, *, check=lambda: None, **changes):
    started = threading.Event()
    args = {"preparation": value.preparation, "request": value.plan.request,
            "plan": value.plan, "claim": _claim(value)}
    args.update(changes)

    def operation():
        started.set()
        return exchange.offer_and_wait(**args, check=check)

    future = pool.submit(operation)
    assert started.wait(2)
    return future


def _endpoint(value, offer):
    mailbox = BRSOwnerPublicationMailbox(value.handoff, worker_thread=offer.thread.ident)
    return _BRSWorkerTerminalEndpoint(mailbox, _PrimitiveExchange(time.monotonic() + 5),
                                      canonical_json(value.handoff.to_dict()), value.plan.plan_sha256,
                                      offer.thread.ident, id(offer.thread))


def _attach(pool, exchange, future):
    exchange.attach_worker(future, pool)


def test_original_preparation_and_endpoint_cross_once_without_native_or_file_writes(prepared, monkeypatch):
    value = prepared
    before = {p: p.read_bytes() for p in value.workspace.rglob("*") if p.is_file()}

    def forbidden(*_a, **_kw):
        pytest.fail("preparation transport wrote native state")

    for name in ("claim_native_episode", "publish_native_episode_result", "write_controller_checkpoint"):
        monkeypatch.setattr(RSILedger, name, forbidden)
    exchange = _exchange(value)
    checks = []

    def check():
        assert not exchange._condition._is_owned()
        checks.append(threading.get_ident())

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, value, check=check)
        _attach(pool, exchange, future)
        offer = exchange.take(check=check)
        assert offer.preparation is value.preparation
        assert offer.request is value.plan.request and offer.plan is value.plan
        assert offer.claim == _claim(value)
        assert type(offer.comparison_bytes) is bytes
        assert offer.thread in pool._threads and offer.thread is not threading.current_thread()
        endpoint = _endpoint(value, offer)
        exchange.return_endpoint(offer, endpoint)
        assert future.result(timeout=2) is endpoint
        assert exchange._state == "consumed"
    assert set(checks) == {threading.get_ident(), offer.thread.ident}
    assert {p: p.read_bytes() for p in value.workspace.rglob("*") if p.is_file()} == before


def test_second_take_poisons_original_waiter(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError, match="take_invalid"):
            exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError, match="unavailable"):
            future.result(timeout=2)
    assert exchange._failed is True and exchange._endpoint is None


def test_second_endpoint_handback_refuses_and_keeps_original_endpoint(prepared):
    exchange = _exchange(prepared)
    entered, received, release = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        endpoint = exchange.offer_and_wait(prepared.preparation, prepared.plan.request,
                                            prepared.plan, _claim(prepared), check=lambda: None)
        received.set()
        assert release.wait(2)
        return endpoint

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation)
        assert entered.wait(2)
        _attach(pool, exchange, future)
        offer = exchange.take(check=lambda: None)
        endpoint = _endpoint(prepared, offer)
        try:
            exchange.return_endpoint(offer, endpoint)
            assert received.wait(2)
            with pytest.raises(RSILearningError, match="duplicate_endpoint"):
                exchange.return_endpoint(offer, endpoint)
            assert exchange._failed is True and exchange._endpoint is endpoint
        finally:
            release.set()
        assert future.result(timeout=2) is endpoint


def test_second_worker_offer_cannot_reset_consumed_exchange(prepared):
    exchange = _exchange(prepared)

    def operation():
        endpoint = exchange.offer_and_wait(prepared.preparation, prepared.plan.request,
                                            prepared.plan, _claim(prepared), check=lambda: None)
        with pytest.raises(RSILearningError, match="duplicate_offer"):
            exchange.offer_and_wait(prepared.preparation, prepared.plan.request,
                                    prepared.plan, _claim(prepared), check=lambda: None)
        return endpoint

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation)
        # The original worker blocks until owner handback.
        _attach(pool, exchange, future)
        offer = exchange.take(check=lambda: None)
        endpoint = _endpoint(prepared, offer)
        exchange.return_endpoint(offer, endpoint)
        assert future.result(timeout=2) is endpoint
    assert exchange._failed is True and exchange._state == "consumed"


@pytest.mark.parametrize("fault", ["before_take", "foreign_offer", "foreign_endpoint", "wrong_worker", "wrong_plan"])
def test_invalid_endpoint_handback_poisons_and_wakes_worker(prepared, fault):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        if fault == "before_take":
            # Wait for its actual offer without consuming owner custody.
            with exchange._condition:
                assert exchange._condition.wait_for(lambda: exchange._offer is not None, timeout=2)
                offer = exchange._offer
        else:
            offer = exchange.take(check=lambda: None)
        endpoint = _endpoint(prepared, offer)
        if fault == "foreign_offer":
            offer = replace(offer)
        elif fault == "foreign_endpoint":
            endpoint = object()
        elif fault == "wrong_worker":
            endpoint._worker_object_id += 1
        elif fault == "wrong_plan":
            endpoint._plan_sha256 = "a" * 64
        with pytest.raises(RSILearningError):
            exchange.return_endpoint(offer, endpoint)
        with pytest.raises(RSILearningError, match="unavailable"):
            future.result(timeout=2)
    assert exchange._failed is True and exchange._endpoint is None


@pytest.mark.parametrize("fault", ["cloned_request", "terminal_claim", "wrong_claim", "foreign_preparation"])
def test_nonoriginal_worker_association_never_enters_offer(prepared, fault):
    exchange = _exchange(prepared)
    changes = {}
    if fault == "cloned_request":
        changes["request"] = SolverRequest.from_dict(prepared.plan.request.to_dict())
    elif fault == "terminal_claim":
        changes["claim"] = replace(_claim(prepared), status="completed")
    elif fault == "wrong_claim":
        changes["claim"] = replace(_claim(prepared), claim_sha256="a" * 64)
    else:
        changes["preparation"] = object()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared, **changes)
        with pytest.raises(RSILearningError):
            future.result(timeout=2)
    assert exchange._failed is True and exchange._offer is None


def test_preparation_drift_after_take_cannot_get_endpoint(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        offer = exchange.take(check=lambda: None)
        prepared.preparation.run.receipt.trusted_execution["changed"] = True
        with pytest.raises(RSILearningError, match="offer_drift"):
            exchange.return_endpoint(offer, _endpoint(prepared, offer))
        with pytest.raises(RSILearningError):
            future.result(timeout=2)
    assert exchange._endpoint is None


def test_replaced_offer_identity_refuses_before_owner_can_take(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        with exchange._condition:
            assert exchange._condition.wait_for(lambda: exchange._offer is not None, timeout=2)
            exchange._offer = replace(exchange._offer)
        with pytest.raises(RSILearningError):
            exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError):
            future.result(timeout=2)
    assert exchange._endpoint is None


@pytest.mark.parametrize("stage", ["take", "handback"])
def test_replaced_nested_plan_refuses_before_foreign_attribute_hook(prepared, stage):
    class ForeignPlan:
        def __getattribute__(self, _name):
            pytest.fail("foreign plan attribute executed")

    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        if stage == "take":
            def mutate():
                with exchange._condition:
                    if exchange._offer is not None:
                        object.__setattr__(exchange._offer, "plan", ForeignPlan())
            with pytest.raises(RSILearningError, match="offer_drift"):
                exchange.take(check=mutate)
        else:
            offer = exchange.take(check=lambda: None)
            endpoint = _endpoint(prepared, offer)
            object.__setattr__(offer, "plan", ForeignPlan())
            with pytest.raises(RSILearningError, match="offer_drift"):
                exchange.return_endpoint(offer, endpoint)
        with pytest.raises(RSILearningError):
            future.result(timeout=2)
    assert exchange._endpoint is None


@pytest.mark.parametrize("position", [3, 4])
def test_foreign_scope_primitive_never_executes_equality(prepared, position):
    class Foreign:
        def __eq__(self, _other):
            pytest.fail("foreign scope equality executed")

    exchange = _exchange(prepared)
    scope = list(exchange._scope)
    scope[position] = Foreign()
    exchange._scope = tuple(scope)
    with pytest.raises(RSILearningError, match="scope_drift"):
        exchange.take(check=lambda: None)


def test_owner_check_failure_wakes_worker_and_preserves_original_error(prepared):
    exchange = _exchange(prepared)
    marker = RuntimeError("inert cancellation")

    def cancelled():
        assert not exchange._condition._is_owned()
        raise marker

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        with pytest.raises(RuntimeError) as observed:
            exchange.take(check=cancelled)
        assert observed.value is marker
        with pytest.raises(RSILearningError, match="unavailable"):
            future.result(timeout=2)


def test_worker_check_failure_wakes_owner_without_offer(prepared):
    exchange = _exchange(prepared)

    def cancelled():
        assert not exchange._condition._is_owned()
        raise RuntimeError("inert worker cancellation")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared, check=cancelled)
        with pytest.raises(RuntimeError):
            future.result(timeout=2)
        with pytest.raises(RSILearningError, match="unavailable"):
            exchange.take(check=lambda: None)
    assert exchange._offer is None


def test_original_deadline_expiry_wakes_owner_and_worker(prepared):
    exchange = _exchange(prepared, deadline=time.monotonic() + .2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError, match="expired"):
            future.result(timeout=2)
        with pytest.raises(RSILearningError, match="unavailable"):
            exchange.take(check=lambda: None)
    assert exchange._endpoint is None


def test_owner_fail_is_permanent_and_wakes_original_worker(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        exchange.take(check=lambda: None)
        exchange.fail()
        with pytest.raises(RSILearningError, match="unavailable"):
            future.result(timeout=2)
        with pytest.raises(RSILearningError, match="unavailable"):
            exchange.take(check=lambda: None)


def test_another_thread_cannot_consume_owner_offer(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool, ThreadPoolExecutor(max_workers=1) as foreign:
        future = _submit(pool, exchange, prepared)
        _attach(pool, exchange, future)
        with pytest.raises(RSILearningError, match="scope_drift"):
            foreign.submit(exchange.take, check=lambda: None).result(timeout=2)
        with pytest.raises(RSILearningError, match="unavailable"):
            future.result(timeout=2)


def test_same_content_different_executor_is_not_original_custody(prepared):
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool, ThreadPoolExecutor(max_workers=1) as foreign:
        future = _submit(pool, exchange, prepared)
        exchange.attach_worker(future, foreign)
        with pytest.raises(RSILearningError, match="offer_drift"):
            exchange.take(check=lambda: None)
        with pytest.raises(RSILearningError):
            future.result(timeout=2)


def test_unconsumed_attempt_objects_are_never_traversed(prepared):
    class Bomb:
        def __getattribute__(self, _name):
            pytest.fail("transport traversed an unused attempt object")

    preparation = replace(prepared.preparation, run=replace(prepared.preparation.run, attempt=Bomb()))
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared, preparation=preparation)
        _attach(pool, exchange, future)
        offer = exchange.take(check=lambda: None)
        assert offer.preparation is preparation
        endpoint = _endpoint(prepared, offer)
        exchange.return_endpoint(offer, endpoint)
        assert future.result(timeout=2) is endpoint


def test_nested_foreign_value_never_executes_comparison_or_serialization(prepared):
    class Bomb:
        def __eq__(self, _other):
            pytest.fail("foreign equality executed")

        def to_dict(self):
            pytest.fail("foreign serializer executed")

    prepared.preparation.run.receipt.trusted_execution["foreign"] = Bomb()
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared)
        with pytest.raises(RSILearningError, match="shape_invalid"):
            future.result(timeout=2)
    assert exchange._offer is None


@pytest.mark.parametrize("fault", ["node_count", "string_bytes", "dto_method_shadow", "scope_type", "claim_type"])
def test_consumed_representation_is_bounded_and_exact_before_handover(prepared, fault):
    changes = {}
    if fault == "node_count":
        prepared.preparation.run.receipt.trusted_execution["large"] = [[0] * 2048] * 17
    elif fault == "string_bytes":
        prepared.preparation.run.receipt.trusted_execution["large"] = "a" * (1024 * 1024 + 1)
    elif fault == "dto_method_shadow":
        def forbidden():
            pytest.fail("shadowed DTO serializer executed")
        object.__getattribute__(prepared.plan.request, "__dict__")["to_dict"] = forbidden
        # The constructor itself must refuse before any serializer executes.
        with pytest.raises(RSILearningError, match="shape_invalid"):
            _exchange(prepared)
        return
    elif fault == "scope_type":
        changes["preparation"] = replace(prepared.preparation,
                                         run=replace(prepared.preparation.run, deadline_scope=[]))
    else:
        changes["claim"] = replace(_claim(prepared), created_at=1)
    exchange = _exchange(prepared)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = _submit(pool, exchange, prepared, **changes)
        with pytest.raises(RSILearningError):
            future.result(timeout=2)
    assert exchange._failed is True and exchange._offer is None


@pytest.mark.parametrize("deadline", [None, True, float("nan"), float("inf"), -1])
def test_unbounded_or_nonprimitive_deadline_refuses(prepared, deadline):
    with pytest.raises(RSILearningError, match="scope_invalid"):
        _BRSNativePreparationExchange(prepared.plan.request,
                                     expected_plan_sha256=prepared.plan.plan_sha256, deadline=deadline)
