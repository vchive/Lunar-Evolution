"""Finite staged transitions plus genuine same-owner ACK/receipt fixtures."""

from __future__ import annotations

import math
import time
from threading import Event, Thread
from types import SimpleNamespace

import pytest
import test_rsi_brs_rejection_provenance as fixture
from test_rsi_brs_rejection_ready_channel import _bound
from test_rsi_python_brs_handoff import _selected_ready

from lunar_evolution import rsi_brs_rejection_ready_ack as ack_graph
from lunar_evolution import rsi_brs_rejection_ready_service as service
from lunar_evolution import rsi_brs_rejection_ready_state as state
from lunar_evolution import rsi_brs_rejection_ready_sync as sync
from lunar_evolution.rsi_learning import RSILearningError

inert_only = fixture.inert_only
sealed_launch = fixture.sealed_launch
tmp_path = fixture.tmp_path


@pytest.mark.parametrize("timeout", [True, False, None, "1", [], 0, -1, 61,
                                    math.inf, -math.inf, math.nan])
def test_timeout_refuses_invalid_values_without_numeric_callbacks(timeout):
    with pytest.raises(RSILearningError, match="service_timeout_invalid"):
        service._timeout(timeout)


def test_timeout_refuses_subclasses_before_conversion():
    calls = []

    class Foreign(float):
        def __float__(self):
            calls.append(True)
            raise AssertionError("foreign conversion")

        def __gt__(self, _other):
            calls.append(True)
            raise AssertionError("foreign comparison")

    with pytest.raises(RSILearningError, match="service_timeout_invalid"):
        service._timeout(Foreign(1))
    assert calls == []


@pytest.mark.parametrize("timeout", [1, 0.001, 60, 60.0])
def test_timeout_accepts_only_finite_positive_bounded_exact_scalars(timeout):
    result = service._timeout(timeout)
    assert type(result) is float and result == timeout


@pytest.mark.parametrize("unix,monotonic,expected", [
    ((), (), 20), ((103,), (), 3), ((), (55,), 5), ((103, 109), (51,), 1),
])
def test_wait_uses_earliest_original_deadline(monkeypatch, unix, monotonic, expected):
    monkeypatch.setattr(service, "_MONOTONIC", lambda: 50.0)
    monkeypatch.setattr(service, "_WALL_TIME", lambda: 100.0)
    assert service._remaining(70.0, unix, monotonic) == expected


@pytest.mark.parametrize("unix,monotonic", [((100,), ()), ((), (50,)), ((99,), ()), ((), (49,))])
def test_expired_original_deadline_is_not_refreshed(monkeypatch, unix, monotonic):
    monkeypatch.setattr(service, "_MONOTONIC", lambda: 50.0)
    monkeypatch.setattr(service, "_WALL_TIME", lambda: 100.0)
    with pytest.raises(RSILearningError, match="service_queue_timeout"):
        service._remaining(70.0, unix, monotonic)


@pytest.mark.parametrize("deadline", [True, None, "120", math.inf, math.nan])
def test_wait_refuses_foreign_or_nonfinite_original_deadline(monkeypatch, deadline):
    monkeypatch.setattr(service, "_MONOTONIC", lambda: 50.0)
    monkeypatch.setattr(service, "_WALL_TIME", lambda: 100.0)
    with pytest.raises(RSILearningError, match="service_deadline_invalid"):
        service._remaining(70.0, (deadline,), ())


def _transport():
    channel, scope = _bound()
    condition = sync.capture_ready_condition(channel._condition)
    owner = SimpleNamespace(_channel=channel, _before_channel_condition=channel._condition,
                            _rejection_ready_state="unused", _rejection_ready_stage=None, _poisoned=False)
    capture = (), (), condition, scope, (), b""
    return owner, capture


def test_timeout_consumes_arm_without_creating_pending_or_ack():
    owner, capture = _transport()
    channel = owner._channel
    with pytest.raises(RSILearningError, match="service_queue_timeout"):
        service._take_ready(owner, capture, time.monotonic() + 0.001, (), ())
    assert owner._rejection_ready_state == "armed"
    assert channel._rejection_ready_worker_guarded is True
    service._preserve_failure(owner, capture[2], None)
    assert owner._rejection_ready_state == "failed" and owner._poisoned is True
    assert channel._closed is True and channel._servicing is False
    assert not channel._queue and channel._requests == {}


def test_armed_worker_guard_cannot_be_reset_before_service_observation():
    owner, capture = _transport()
    channel, errors = owner._channel, []

    def reset_guard():
        try:
            with channel._condition:
                while not channel._rejection_ready_worker_guarded:
                    assert channel._condition.wait(5)
                channel._rejection_ready_worker_guarded = False
                channel._condition.notify_all()
        except BaseException as error:  # noqa: BLE001 - retain thread outcome.
            errors.append(error)

    thread = Thread(target=reset_guard, daemon=True)
    thread.start()
    try:
        with pytest.raises(RSILearningError, match="service_worker_guard_drift"):
            service._take_ready(owner, capture, time.monotonic() + 5, (), ())
    finally:
        service._preserve_failure(owner, capture[2], None)
        thread.join(5)
    assert not thread.is_alive() and errors == []
    assert owner._poisoned is True and channel._closed is True
    assert not channel._queue and channel._requests == {}


def _post_when_armed(channel, scope, release, results, errors):
    try:
        with channel._condition:
            while not channel._rejection_ready_worker_guarded:
                assert channel._condition.wait(5)
        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                assert release.wait(5)

        results.append(channel.request(_selected_ready(scope[1]), check=check))
    except BaseException as exc:  # noqa: BLE001 - preserve every thread outcome.
        errors.append(exc)


@pytest.mark.parametrize("prefix", ["none", "ack", "fields", "both"])
def test_failure_preserves_exact_assigned_ack_prefix_and_original_pending(prefix):
    owner, capture = _transport()
    channel, scope = owner._channel, capture[3]
    release, results, errors = Event(), [], []
    thread = Thread(target=_post_when_armed, args=(channel, scope, release, results, errors), daemon=True)
    thread.start()
    try:
        capsule = service._take_ready(owner, capture, time.monotonic() + 5, (), ())
        pending = capsule[2][7]
        assert owner._rejection_ready_stage is capsule
        state.assert_selected_ready_inflight(channel, capsule)
        assert pending.ack is None and pending.ack_fields is None and not channel._queue
        fields = scope[0], scope[1], capsule[3][3], "a" * 64
        ack = ack_graph.build_rejection_ready_ack(fields)
        with channel._condition:
            if prefix in {"ack", "both"}:
                service._set_pending(pending, "ack", ack)
            if prefix in {"fields", "both"}:
                service._set_pending(pending, "ack_fields", fields)
        service._preserve_failure(owner, capture[2], capsule)
        assert owner._rejection_ready_state == "failed" and owner._poisoned is True
        assert channel._requests[scope[1]] is pending and owner._rejection_ready_stage is capsule
        assert pending.ack is (ack if prefix in {"ack", "both"} else None)
        assert pending.ack_fields is (fields if prefix in {"fields", "both"} else None)
        assert pending.error == "handler_failed" and channel._servicing is False and channel._closed is True
    finally:
        # The close/notification happened before this bounded join, without an
        # observation mutex held. Never use the legacy service cleanup here.
        channel.close()
        release.set()
        thread.join(5)
        assert not thread.is_alive()
    assert results == [] and len(errors) == 1


def _prepare(value):
    value.owner.retain_rejected_terminal(value.terminal)
    value.owner.retain_rejection_provenance()
    value.owner.retain_rejection_ready_capture()


def _release_original_worker_when_armed(value, errors):
    try:
        channel = value.wave.channel
        with channel._condition:
            while not channel._rejection_ready_worker_guarded:
                assert channel._condition.wait(20)
        value.ready.set()
    except BaseException as exc:  # noqa: BLE001 - preserve every thread outcome.
        errors.append(exc)


@pytest.mark.parametrize("count", [1, 2])
def test_original_owner_staged_ack_preserves_durable_state_and_worker_receipt(tmp_path, monkeypatch, count):
    with fixture.c1._waiting(tmp_path, monkeypatch, count=count) as value:
        _prepare(value)
        original = fixture.c1.owner_fixture._capture(value)
        materials = fixture.c1._native_material_snapshot(value)
        capture = value.owner._rejection_ready_capture
        release_errors = []
        release = Thread(target=_release_original_worker_when_armed, args=(value, release_errors), daemon=True)
        release.start()
        try:
            digest = value.owner.service_rejection_ready(timeout=20)
            assert digest == capture[4][2]
            owner = value.owner
            assert owner._rejection_ready_state == "committed" and owner._poisoned is False
            assert owner._rejection_ready_commit_started is True
            capsule, ack, fields = owner._rejection_ready_stage, owner._rejection_ready_ack, owner._rejection_ready_ack_fields
            state.assert_selected_ready_committed(value.wave.channel, capsule, ack, fields)
            # Actual worker receipt is observed separately after service released
            # observation and channel locks. This does not settle its outcome.
            assert value.messages.get(timeout=20) == digest
            assert release_errors == []
            fixture.c1.owner_fixture._unchanged(value, original)
            assert fixture.c1._native_material_snapshot(value) == materials
            assert owner._phase == "rejected-provenance" and value.wave.state["executions"] == {}
            assert value.wave.selected_return is None and value.wave.selected_settlement_started is False
            assert value.ledger.episode_result(value.episode_id) is None
            assert value.wave.channel._completed_selected_episodes == set()
        finally:
            value.wave.channel.close()
            value.ready.set()
            release.join(20)
            assert not release.is_alive()


def test_original_owner_timeout_is_permanent_and_does_not_charge_or_register(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _prepare(value)
        original = fixture.c1.owner_fixture._capture(value)
        capture = value.owner._rejection_ready_capture
        with pytest.raises(RSILearningError, match="service_queue_timeout"):
            value.owner.service_rejection_ready(timeout=0.001)
        assert value.owner._rejection_ready_state == "failed" and value.owner._poisoned is True
        assert value.owner._rejection_ready_capture is capture
        assert value.wave.channel._closed is True and value.wave.channel._rejection_ready_worker_guarded is True
        assert value.owner._rejection_ready_stage is None and value.owner._rejection_ready_commit_started is False
        assert value.wave.channel._requests == {} and not value.wave.channel._queue
        with pytest.raises(RSILearningError):
            value.owner.service_rejection_ready(timeout=1)
        fixture.c1.owner_fixture._unchanged(value, original)
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("name", ["_owner", "_timeout", "_take_ready", "_preserve_failure"])
def test_entry_refuses_replaced_service_helpers_before_callback(monkeypatch, name):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)

    with monkeypatch.context() as patch:
        patch.setattr(service, name, forbidden)
        with pytest.raises(RSILearningError, match="service_graph_drift"):
            service.service_rejection_ready(object(), timeout=1)
    assert calls == []


@pytest.mark.parametrize("name", ["_owner", "_timeout", "_take_ready"])
def test_entry_refuses_mutated_held_helper_code_before_callback(monkeypatch, name):
    function = getattr(service, name)
    with monkeypatch.context() as patch:
        patch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
        with pytest.raises(RSILearningError, match="service_graph_drift"):
            service.service_rejection_ready(object(), timeout=1)


@pytest.mark.parametrize("index", [0, 2])
def test_entry_independently_guards_bootstrap_and_its_refusal_code(monkeypatch, index):
    function = service._SERVICE_FUNCTIONS[index]
    with monkeypatch.context() as patch:
        patch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
        with pytest.raises(RSILearningError, match="service_graph_drift"):
            service.service_rejection_ready(object(), timeout=1)


def test_entry_refusal_avoids_a_changed_application_exception_initializer(monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("application exception initializer called")

    with monkeypatch.context() as patch:
        patch.setattr(service, "_owner", forbidden)
        patch.setattr(RSILearningError, "__init__", forbidden)
        with pytest.raises(RSILearningError, match="service_graph_drift") as failure:
            service.service_rejection_ready(object(), timeout=1)
        assert failure.value.code == "rsi_brs_rejection_ready_service_graph_drift"
    assert calls == []


def test_native_failure_handler_does_not_dispatch_changed_transport_helpers(monkeypatch):
    owner, capture = _transport()
    close = service._make_failure_handler(owner, capture[2])
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("changed transport helper called")

    with monkeypatch.context() as patch:
        patch.setattr(service.queued, "_namespace", forbidden)
        patch.setattr(service, "_set_pending", forbidden)
        patch.setattr(service, "_NOTIFY_ALL", forbidden)
        patch.setattr(service.sync, "assert_ready_condition", forbidden)
        close(None)
    assert calls == []
    assert owner._rejection_ready_state == "failed" and owner._poisoned is True
    assert owner._channel._closed is True and owner._channel._servicing is False


@pytest.mark.parametrize("target", ["namespace", "remaining", "wait"])
def test_wait_reentry_checks_original_graph_before_replaced_worker_callback_target(monkeypatch, target):
    owner, capture = _transport()
    channel, scope = owner._channel, capture[3]
    close = service._make_failure_handler(owner, capture[2])
    release, results, errors, called = Event(), [], [], []
    patch = monkeypatch.context()

    def forbidden(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("replaced service helper executed after wait")

    def work():
        try:
            with channel._condition:
                while not channel._rejection_ready_worker_guarded:
                    assert channel._condition.wait(5)
            calls = 0

            def check():
                nonlocal calls
                calls += 1
                if calls == 1:
                    if target == "namespace":
                        patcher.setattr(service.queued, "_namespace", forbidden)
                    else:
                        patcher.setattr(service, "_remaining" if target == "remaining" else "_WAIT", forbidden)
                elif calls == 2:
                    assert release.wait(5)

            results.append(channel.request(_selected_ready(scope[1]), check=check))
        except BaseException as exc:  # noqa: BLE001 - preserve every thread outcome.
            errors.append(exc)

    with patch as patcher:
        thread = Thread(target=work, daemon=True)
        thread.start()
        try:
            with pytest.raises(RSILearningError, match="service_graph_drift"):
                service._take_ready(owner, capture, time.monotonic() + 5, (), ())
            assert called == []
            close(None)
        finally:
            release.set()
            thread.join(5)
            assert not thread.is_alive()
    assert results == [] and len(errors) == 1 and called == []
    assert owner._rejection_ready_state == "failed" and owner._poisoned is True


def test_original_owner_early_natural_ready_refuses_and_retains_original_pending(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _prepare(value)
        original = fixture.c1.owner_fixture._capture(value)
        capture = value.owner._rejection_ready_capture
        channel = value.wave.channel
        value.ready.set()
        # Retain the original condition only while checking the early refusal;
        # no dynamic semantic observation can start before the empty gate fails.
        with channel._condition:
            expiry = time.monotonic() + 20
            while not channel._queue:
                remaining = expiry - time.monotonic()
                assert remaining > 0 and channel._condition.wait(remaining)
            pending = channel._queue[0]
            assert channel._requests[value.episode_id] is pending
            with pytest.raises(RSILearningError):
                value.owner.service_rejection_ready(timeout=1)
            assert channel._requests[value.episode_id] is pending and channel._queue[0] is pending
            assert pending.ack is None and pending.ack_fields is None
            assert value.owner._rejection_ready_state == "failed" and value.owner._poisoned is True
            assert value.owner._rejection_ready_stage is None and value.owner._rejection_ready_commit_started is False
            assert value.owner._rejection_ready_capture is capture
        fixture.c1.owner_fixture._unchanged(value, original)
        assert value.ledger.episode_result(value.episode_id) is None


def test_original_owner_inflight_callback_refusal_closes_before_receipt_and_preserves_scope(tmp_path, monkeypatch):
    active = {}

    def cancelled():
        value = active.get("value")
        if value is not None and value.owner._rejection_ready_state == "inflight":
            active["called"] = True
            raise RSILearningError("fixture_staged_inflight_refusal")
        return False

    monkeypatch.setattr(fixture.c1, "_unlocked_cancelled", cancelled)
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _prepare(value)
        original = fixture.c1.owner_fixture._capture(value)
        active["value"] = value
        release_errors = []
        release = Thread(target=_release_original_worker_when_armed, args=(value, release_errors), daemon=True)
        release.start()
        try:
            with pytest.raises(RSILearningError, match="fixture_staged_inflight_refusal"):
                value.owner.service_rejection_ready(timeout=20)
            assert active["called"] is True and release_errors == []
            owner = value.owner
            pending = owner._rejection_ready_stage[2][7]
            assert owner._rejection_ready_state == "failed" and owner._poisoned is True
            assert owner._rejection_ready_commit_started is False
            assert pending.ack is None and pending.ack_fields is None
            assert value.wave.channel._requests[value.episode_id] is pending
            assert value.wave.channel._closed is True and value.wave.channel._servicing is False
            assert value.messages.empty()
            fixture.c1.owner_fixture._unchanged(value, original)
            assert value.ledger.episode_result(value.episode_id) is None
        finally:
            value.wave.channel.close()
            value.ready.set()
            release.join(20)
            assert not release.is_alive()


def test_original_owner_notification_uncertainty_retains_full_ack_and_permanent_failed_scope(tmp_path, monkeypatch):
    import sys
    from threading import Condition

    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _prepare(value)
        original = fixture.c1.owner_fixture._capture(value)
        owner = value.owner
        notify_code = Condition.notify_all.__code__
        injected = []
        previous = sys.getprofile()

        def fault(frame, event, _argument):
            # A fixture-only interpreter fault at the original notify call does
            # not replace source, classes, descriptors or any trusted function.
            if event == "call" and frame.f_code is notify_code and owner._rejection_ready_commit_started is True:
                pending = owner._rejection_ready_stage[2][7]
                injected.append((pending.ack, pending.ack_fields))
                raise RSILearningError("fixture_staged_notify_uncertain")

        release_errors = []
        release = Thread(target=_release_original_worker_when_armed, args=(value, release_errors), daemon=True)
        release.start()
        try:
            sys.setprofile(fault)
            with pytest.raises(RSILearningError, match="fixture_staged_notify_uncertain"):
                owner.service_rejection_ready(timeout=20)
        finally:
            sys.setprofile(previous)
            value.wave.channel.close()
            value.ready.set()
            release.join(20)
            assert not release.is_alive()
        assert len(injected) == 1 and release_errors == []
        ack, fields = injected[0]
        pending = owner._rejection_ready_stage[2][7]
        assert pending.ack is ack is owner._rejection_ready_ack
        assert pending.ack_fields is fields is owner._rejection_ready_ack_fields
        assert owner._rejection_ready_commit_started is True
        assert owner._rejection_ready_state == "failed" and owner._poisoned is True
        assert value.wave.channel._requests[value.episode_id] is pending
        assert value.wave.channel._closed is True and value.wave.channel._servicing is False
        # Complete fields can become visible when the lock unwinds. An uncertain
        # notify does not establish either receipt or nonreceipt of this ACK.
        fixture.c1.owner_fixture._unchanged(value, original)
        assert value.ledger.episode_result(value.episode_id) is None
