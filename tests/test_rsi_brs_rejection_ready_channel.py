"""Passive selected-ready observations over a real inert worker request."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from threading import Event, Thread, get_ident

import pytest
from test_rsi_python_brs_handoff import CONTEXT, RUN, _preflight, _selected_ready, _wire

import lunar_evolution.rsi_brs_rejection_ready_channel as observer
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_admission import (
    BRSAdmissionChannel,
    BRSAdmissionReady,
    _Pending,
)
from lunar_evolution.rsi_python_brs_handoff import BRSSelectedChildHandoff


def _bound():
    preflight = _preflight(_wire(executions=[]))
    handoff = BRSSelectedChildHandoff.from_selection(
        preflight.select_next_pending(), CONTEXT, lease_nonce="Q" * 32,
    )
    episodes = tuple(item[1] for item in preflight.intents)
    channel = BRSAdmissionChannel(RUN, episodes, owner_thread=get_ident())
    channel.bind_selected_handoff(handoff, preflight, CONTEXT)
    scope = (RUN, handoff.episode_id, handoff.sha256, handoff.lease_nonce, episodes, get_ident())
    return channel, scope


@pytest.fixture
def queued():
    channel, scope = _bound()
    posted, release, errors, results = Event(), Event(), [], []
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 2:
            posted.set()  # request() already enqueued its original detached ready.
            assert release.wait(5)

    def work():
        try:
            results.append(channel.request(_selected_ready(scope[1]), check=check))
        except BaseException as exc:  # noqa: BLE001 - retain every worker outcome.
            errors.append(exc)

    thread = Thread(target=work, daemon=True)
    thread.start()
    try:
        assert posted.wait(5)
        yield channel, scope, thread, errors, results
    finally:
        # Every fault test restores its mutations before reaching this finally.
        channel.close()
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert results == []
        assert len(errors) == 1
        assert str(errors[0]) == "rsi_python_brs_admission_closed"


@contextmanager
def _changed(target, name, value):
    original = getattr(target, name)
    object.__setattr__(target, name, value)
    try:
        yield
    finally:
        object.__setattr__(target, name, original)


def _capture(queued):
    channel, scope, *_ = queued
    return observer.capture_selected_ready_stage(channel, expected_scope=scope)


def _pending(queued):
    return queued[0]._requests[queued[1][1]]


def test_original_queued_capsule_is_passive_immutable_and_retains_identities(queued):
    channel, scope, thread, errors, results = queued
    pending = _pending(queued)
    before = (pending.state, pending.ack, pending.ack_fields, pending.error, pending.cancelled,
              tuple(channel._queue), dict(channel._requests), channel._servicing)
    capsule = _capture(queued)
    assert type(capsule) is tuple and capsule[0] == scope
    with pytest.raises(TypeError):
        capsule[0] = scope
    assert capsule[2] == (channel, channel._condition, channel._queue, channel._requests,
                          channel._episode_ids, channel._consumed_handoff_nonces,
                          channel._completed_selected_episodes, pending, pending.ready)
    observer.assert_selected_ready_stage(channel, capsule)
    assert (pending.state, pending.ack, pending.ack_fields, pending.error, pending.cancelled,
            tuple(channel._queue), dict(channel._requests), channel._servicing) == before
    assert thread.is_alive() and results == [] and errors == []


def test_empty_channel_refuses_without_arming_or_waiting():
    channel, scope = _bound()
    with pytest.raises(RSILearningError, match="state_invalid"):
        observer.capture_selected_ready_stage(channel, expected_scope=scope)
    assert channel._requests == {} and not channel._queue and channel._servicing is False
    assert channel._closed is False
    channel.close()


@pytest.mark.parametrize("target", ["queue", "requests", "episodes", "nonces", "completed"])
def test_equal_container_replacement_refuses_original_identity(queued, target):
    channel, *_ = queued
    capsule = _capture(queued)
    name, replacement = {
        "queue": ("_queue", deque(channel._queue)),
        "requests": ("_requests", dict(channel._requests)),
        "episodes": ("_episode_ids", frozenset(list(channel._episode_ids))),
        "nonces": ("_consumed_handoff_nonces", set(channel._consumed_handoff_nonces)),
        "completed": ("_completed_selected_episodes", set()),
    }[target]
    assert replacement is not getattr(channel, name)
    with _changed(channel, name, replacement), pytest.raises(RSILearningError, match="identity_changed"):
        observer.assert_selected_ready_stage(channel, capsule)


def test_bounded_queue_refuses_before_initial_capture_and_does_not_move_request(queued):
    channel, *_ = queued
    pending = _pending(queued)
    replacement = deque(channel._queue, maxlen=1)
    with _changed(channel, "_queue", replacement):
        with pytest.raises(RSILearningError, match="state_invalid"):
            _capture(queued)
        assert tuple(replacement) == (pending,)
        assert pending.state == "queued" and pending.ack is None


def test_equal_reconstructed_pending_refuses(queued):
    channel, scope, *_ = queued
    capsule = _capture(queued)
    pending = _pending(queued)
    clone = _Pending(pending.ready, binding_sha256=pending.binding_sha256)
    with (_changed(channel, "_requests", {scope[1]: clone}),
          _changed(channel, "_queue", deque([clone])),
          pytest.raises(RSILearningError, match="identity_changed")):
        observer.assert_selected_ready_stage(channel, capsule)


def test_equal_reconstructed_detached_ready_refuses(queued):
    capsule = _capture(queued)
    pending = _pending(queued)
    ready = pending.ready
    clone = BRSAdmissionReady(ready.run_id, ready.episode_id, ready.payload, ready.request_sha256)
    with _changed(pending, "ready", clone), pytest.raises(RSILearningError, match="identity_changed"):
        observer.assert_selected_ready_stage(queued[0], capsule)


@pytest.mark.parametrize("name,value", [
    ("_closed", True), ("_servicing", True), ("_handoff_mode", False),
    ("_selected_episode_id", "other"), ("_selected_handoff_sha256", "f" * 64),
    ("_run_id", "foreign-run"), ("_owner_thread", 1),
    ("_consumed_handoff_nonces", {"R" * 32}), ("_completed_selected_episodes", {"foreign"}),
    ("_requests", {}), ("_queue", deque()),
])
def test_channel_field_drift_refuses_without_mutation_or_ack(queued, name, value):
    capsule = _capture(queued)
    with _changed(queued[0], name, value), pytest.raises(RSILearningError, match="state_invalid"):
        observer.assert_selected_ready_stage(queued[0], capsule)
    assert _pending(queued).ack is None


@pytest.mark.parametrize("name,value", [
    ("state", "inflight"), ("state", "done"), ("binding_sha256", "f" * 64),
    ("cancelled", True), ("error", "closed"), ("ack", object()), ("ack_fields", ("x",) * 4),
])
def test_pending_field_drift_refuses_and_preserves_evidence(queued, name, value):
    capsule = _capture(queued)
    pending = _pending(queued)
    with _changed(pending, name, value):
        with pytest.raises(RSILearningError, match="state_invalid"):
            observer.assert_selected_ready_stage(queued[0], capsule)
        # The helper must not run cleanup for a state it does not own.
        assert getattr(pending, name) is value
    assert pending.ack is None and pending.error is None


@pytest.mark.parametrize("name,value", [
    ("run_id", "foreign-run"), ("episode_id", "foreign-episode"),
    ("payload", b"other comparison bytes"), ("request_sha256", "f" * 64),
])
def test_ready_primitive_drift_refuses_without_refresh(queued, name, value):
    capsule = _capture(queued)
    ready = _pending(queued).ready
    with _changed(ready, name, value), pytest.raises(RSILearningError, match="state_invalid|ready_changed"):
        observer.assert_selected_ready_stage(queued[0], capsule)
    observer.assert_selected_ready_stage(queued[0], capsule)


@pytest.mark.parametrize("value", [None, (), [], ("run",) * 6])
def test_scope_shape_refuses_before_condition_access(queued, value):
    with _changed(queued[0], "_condition", object()), pytest.raises(RSILearningError, match="scope_invalid"):
        observer.capture_selected_ready_stage(queued[0], expected_scope=value)


@pytest.mark.parametrize("index,value", [
    (0, "bad run"), (1, "foreign"), (2, "0" * 64), (3, "short"),
    (4, ()), (4, ("same", "same")), (4, ("bad id",)), (4, ("x",) * 9),
    (5, True), (5, 0), (5, 2**64),
])
def test_scope_invalid_domains_refuse(queued, index, value):
    scope = list(queued[1])
    scope[index] = value
    with pytest.raises(RSILearningError, match="scope_invalid"):
        observer.capture_selected_ready_stage(queued[0], expected_scope=tuple(scope))


def test_scope_does_not_introduce_a_disjoint_run_and_episode_domain_requirement():
    # This is a primitive shape check, not a handoff/ordinal semantic validator.
    scope = (RUN, RUN, "a" * 64, "Q" * 32, (RUN,), get_ident())
    assert observer._scope(scope) is scope


class _Trap:
    def __init__(self):
        self.calls = []

    def __hash__(self):
        self.calls.append("hash")
        return 123

    def __eq__(self, other):
        self.calls.append("eq")
        raise AssertionError("foreign equality")


@pytest.mark.parametrize("target", ["scope-run", "scope-thread", "scope-episode", "request-key",
                                     "nonce", "episode-set", "channel-key", "pending-state",
                                     "ready-payload"])
def test_foreign_values_refuse_before_hash_or_equality(queued, target):
    channel, scope, *_ = queued
    trap = _Trap()
    pending = _pending(queued)
    if target.startswith("scope-"):
        values = list(scope)
        if target == "scope-episode":
            values[4] = (trap, scope[1])
        else:
            values[0 if target == "scope-run" else 5] = trap
        with pytest.raises(RSILearningError, match="scope_invalid"):
            observer.capture_selected_ready_stage(channel, expected_scope=tuple(values))
    elif target == "channel-key":
        namespace = channel.__dict__
        original = dict(namespace)
        del namespace["_run_id"]
        namespace[trap] = None  # Keep the original length, forcing an exact-key check.
        trap.calls.clear()
        try:
            with pytest.raises(RSILearningError, match="channel_invalid"):
                _capture(queued)
            assert trap.calls == []
        finally:
            namespace.clear()  # Clearing avoids calling the foreign key's hash/equality.
            namespace.update(original)
    else:
        if target == "request-key":
            obj, name, value = channel, "_requests", {trap: pending}
        elif target == "nonce":
            obj, name, value = channel, "_consumed_handoff_nonces", {trap}
        elif target == "episode-set":
            obj, name, value = channel, "_episode_ids", frozenset((trap, scope[1]))
        elif target == "pending-state":
            obj, name, value = pending, "state", trap
        else:
            obj, name, value = pending.ready, "payload", trap
        trap.calls.clear()
        with _changed(obj, name, value), pytest.raises(RSILearningError, match="state_invalid"):
            _capture(queued)
    assert trap.calls == []


@pytest.mark.parametrize("kind,name", [
    (_Pending, "ready"), (_Pending, "state"), (_Pending, "ack"),
    (BRSAdmissionReady, "payload"), (BRSAdmissionReady, "request_sha256"),
    (_Pending, "__getattribute__"), (BRSAdmissionReady, "__getattribute__"),
    (_Pending, "__getattr__"), (BRSAdmissionChannel, "__getattribute__"),
])
def test_class_property_or_lookup_replacement_refuses_before_callback(queued, monkeypatch, kind, name):
    calls = []

    def trap(*args):
        calls.append("callback")
        raise AssertionError("foreign descriptor callback")

    with monkeypatch.context() as changes:
        changes.setattr(kind, name, trap if name.startswith("__get") else property(trap), raising=False)
        with pytest.raises(RSILearningError, match="class_drift"):
            _capture(queued)
        assert calls == []


def test_dto_serializers_and_json_are_not_observation_dependencies(queued, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("DTO validation is outside the passive observer")

    with monkeypatch.context() as changes:
        changes.setattr(BRSAdmissionReady, "__post_init__", forbidden)
        changes.setattr(observer.admission.json, "loads", forbidden)
        capsule = _capture(queued)
        observer.assert_selected_ready_stage(queued[0], capsule)


def test_thread_reader_shadow_refuses_before_calling_replacement(queued, monkeypatch):
    calls = []

    def replacement():
        calls.append("thread")
        raise AssertionError("replacement thread reader called")

    with monkeypatch.context() as changes:
        changes.setattr(observer, "get_ident", replacement)
        with pytest.raises(RSILearningError, match="thread_binding_drift"):
            _capture(queued)
    assert calls == []


def test_ready_primitive_checks_do_not_call_regex_under_native_lock(queued, monkeypatch):
    condition = queued[0]._condition
    original = observer._SHA
    calls = []

    class OutsidePattern:
        def fullmatch(self, value):
            assert not condition._lock._is_owned()
            calls.append("scope")
            return original.fullmatch(value)

    with monkeypatch.context() as changes:
        changes.setattr(observer, "_SHA", OutsidePattern())
        capsule = _capture(queued)
        observer.assert_selected_ready_stage(queued[0], capsule)
    assert calls == ["scope", "scope"]


def test_foreign_owner_thread_cannot_capture(queued):
    errors = []

    def work():
        try:
            _capture(queued)
        except RSILearningError as exc:
            errors.append(str(exc))

    thread = Thread(target=work)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert errors == ["rsi_brs_rejection_ready_channel_state_invalid"]


def test_existing_duplicate_ready_refusal_and_original_queue_remain_unchanged(queued):
    channel, scope, *_ = queued
    capsule = _capture(queued)
    errors = []

    def duplicate():
        try:
            channel.request(_selected_ready(scope[1]), check=lambda: None)
        except RSILearningError as exc:
            errors.append(str(exc))

    thread = Thread(target=duplicate)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert errors == ["rsi_python_brs_admission_duplicate_request"]
    observer.assert_selected_ready_stage(channel, capsule)


@pytest.mark.parametrize("value", [None, (), [], (None,) * 4])
def test_malformed_capsule_refuses(queued, value):
    with pytest.raises(RSILearningError):
        observer.assert_selected_ready_stage(queued[0], value)


def test_different_channel_cannot_reuse_capsule(queued):
    capsule = _capture(queued)
    other, _ = _bound()
    try:
        with pytest.raises(RSILearningError, match="capsule_invalid"):
            observer.assert_selected_ready_stage(other, capsule)
    finally:
        other.close()
