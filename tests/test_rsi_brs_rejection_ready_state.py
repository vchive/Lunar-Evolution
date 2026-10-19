"""Transport-state observations retain actual queued worker identities only."""

from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType

import pytest
import test_rsi_brs_rejection_ready_channel as queued_tests
from test_rsi_brs_rejection_ready_channel import _capture, _changed, _pending

from lunar_evolution import rsi_brs_rejection_ready_ack as ack_graph
from lunar_evolution import rsi_brs_rejection_ready_channel as queued_reader
from lunar_evolution import rsi_brs_rejection_ready_state as state
from lunar_evolution import rsi_learning as learning
from lunar_evolution.rsi_learning import RSILearningError

queued = queued_tests.queued


@contextmanager
def _inflight(value):
    channel, *_rest = value
    capsule = _capture(value)
    pending = _pending(value)
    # Exercise the new passive reader over the original natural pending. These
    # fixture-only assignments do not test or grant a production service path.
    with channel._condition:
        assert channel._queue.popleft() is pending
        pending.state = "inflight"
        channel._servicing = True
    try:
        yield capsule, pending
    finally:
        with channel._condition:
            pending.state, pending.ack, pending.ack_fields = "queued", None, None
            channel._servicing = False
            channel._queue.append(pending)


def _fields(capsule):
    run, episode, _payload, digest = capsule[3]
    return run, episode, digest, "a" * 64


def test_inflight_reader_preserves_original_pending_without_ack(queued):
    with _inflight(queued) as (capsule, pending):
        state.assert_selected_ready_inflight(queued[0], capsule)
        assert pending.state == "inflight" and pending.ack is None and pending.ack_fields is None
        assert queued[0]._servicing is True and not queued[0]._queue
        assert queued[4] == []
        # The older queued observer deliberately retains its original refusal.
        with pytest.raises(RSILearningError):
            queued_reader.assert_selected_ready_stage(queued[0], capsule)


def test_committed_reader_checks_original_ack_and_all_fields_without_worker_receipt(queued):
    with _inflight(queued) as (capsule, pending):
        fields = _fields(capsule)
        ack = ack_graph.build_rejection_ready_ack(fields)
        with (_changed(pending, "state", "done"), _changed(pending, "ack", ack),
              _changed(pending, "ack_fields", fields), _changed(queued[0], "_servicing", False)):
            state.assert_selected_ready_committed(queued[0], capsule, ack, fields)
            assert pending.ack is ack and pending.ack_fields is fields and queued[4] == []


@pytest.mark.parametrize("field,value", [
    ("state", "queued"), ("state", "done"), ("binding_sha256", "f" * 64),
    ("error", "closed"), ("cancelled", True), ("ack", object()), ("ack_fields", ("x",) * 4),
])
def test_inflight_drift_refuses_and_never_clears_evidence(queued, field, value):
    with _inflight(queued) as (capsule, pending), _changed(pending, field, value):
        with pytest.raises(RSILearningError):
            state.assert_selected_ready_inflight(queued[0], capsule)
        assert getattr(pending, field) is value


@pytest.mark.parametrize("field,value", [
    ("_closed", True), ("_servicing", False), ("_selected_episode_id", "foreign"),
    ("_selected_handoff_sha256", "f" * 64), ("_owner_thread", True),
    ("_completed_selected_episodes", {"foreign"}),
])
def test_inflight_channel_shape_and_scope_remain_exact(queued, field, value):
    with (_inflight(queued) as (capsule, _pending), _changed(queued[0], field, value),
          pytest.raises(RSILearningError)):
        state.assert_selected_ready_inflight(queued[0], capsule)


@pytest.mark.parametrize("target", ["pending", "ready", "requests", "queue"])
def test_equal_reconstruction_never_replaces_original_identity(queued, target):
    with _inflight(queued) as (capsule, pending):
        if target == "pending":
            clone = replace(pending)
            change = _changed(queued[0], "_requests", {capsule[0][1]: clone})
        elif target == "ready":
            change = _changed(pending, "ready", replace(pending.ready))
        elif target == "requests":
            change = _changed(queued[0], "_requests", dict(queued[0]._requests))
        else:
            change = _changed(queued[0], "_queue", type(queued[0]._queue)())
        with change, pytest.raises(RSILearningError):
            state.assert_selected_ready_inflight(queued[0], capsule)


@pytest.mark.parametrize("fault", ["ack", "fields", "record", "servicing", "error", "cancelled"])
def test_committed_incomplete_or_reconstructed_ack_refuses_without_rollback(queued, fault):
    with _inflight(queued) as (capsule, pending):
        fields = _fields(capsule)
        ack = ack_graph.build_rejection_ready_ack(fields)
        with (_changed(pending, "state", "done"), _changed(pending, "ack", ack),
              _changed(pending, "ack_fields", fields), _changed(queued[0], "_servicing", False)):
            target, name, value = {
                "ack": (pending, "ack", replace(ack)),
                "fields": (pending, "ack_fields", (*fields,)),
                "record": (ack, "record_sha256", "f" * 64),
                "servicing": (queued[0], "_servicing", True),
                "error": (pending, "error", "closed"),
                "cancelled": (pending, "cancelled", True),
            }[fault]
            with _changed(target, name, value), pytest.raises(RSILearningError):
                state.assert_selected_ready_committed(queued[0], capsule, ack, fields)
            assert pending.ack is ack and pending.ack_fields is fields


@pytest.mark.parametrize("function", ["_namespace", "_slot", "_scope", "_ready_fields"])
def test_replaced_reader_is_rejected_before_its_callback(queued, monkeypatch, function):
    with _inflight(queued) as (capsule, _pending):
        calls = []

        def forbidden(*_args, **_kwargs):
            calls.append(True)

        with monkeypatch.context() as patch:
            patch.setattr(queued_reader, function, forbidden)
            with pytest.raises(RSILearningError):
                state.assert_selected_ready_inflight(queued[0], capsule)
        assert calls == []


def test_non_string_request_key_is_refused_before_hash_or_equality(queued):
    class Key:
        def __hash__(self):
            return 1

        def __eq__(self, _other):
            raise AssertionError("foreign key equality executed")

    with (_inflight(queued) as (capsule, pending),
          _changed(queued[0], "_requests", {Key(): pending}), pytest.raises(RSILearningError)):
        state.assert_selected_ready_inflight(queued[0], capsule)


@pytest.mark.parametrize("capsule", [None, (), [], (None,) * 4])
def test_malformed_capsule_never_touches_a_channel_callback(capsule):
    class Foreign:
        def __getattribute__(self, _name):
            raise AssertionError("foreign lookup executed")

    with pytest.raises(RSILearningError):
        state.assert_selected_ready_inflight(Foreign(), capsule)


@pytest.mark.parametrize("target", ["invalid-channel", "invalid-scope", "class-drift"])
def test_refusal_never_invokes_a_changed_application_error_initializer(monkeypatch, target):
    calls = []

    def changed(self, code):
        calls.append(code)
        BaseException.__init__(self, code)

    if target == "invalid-channel":
        channel, capsule = object(), ()
    else:
        channel = object.__new__(queued_reader._CHANNEL)
        capsule = (None,) * 4
    with monkeypatch.context() as patch:
        patch.setattr(learning.RSILearningError, "__init__", changed)
        if target == "class-drift":
            patch.setattr(queued_reader._PENDING, "__slots__", ("foreign",))
        with pytest.raises(RSILearningError, match="ready_state_invalid") as failure:
            state.assert_selected_ready_inflight(channel, capsule)
        assert failure.value.code == "rsi_brs_rejection_ready_state_invalid"
    assert calls == []


@pytest.mark.parametrize("declared", [queued_reader._PENDING, queued_reader._READY])
@pytest.mark.parametrize("name,value", [
    ("__slots__", ("foreign",)), ("__annotations__", {"foreign": str}),
    ("__dataclass_fields__", {}), ("__dataclass_params__", object()),
])
def test_original_transport_declaration_metadata_cannot_change(declared, name, value, monkeypatch):
    monkeypatch.setattr(declared, name, value)
    with pytest.raises(RSILearningError, match="ready_state_invalid"):
        state._STATE_FUNCTIONS[1]()


@pytest.mark.parametrize("declared", [queued_reader._PENDING, queued_reader._READY])
def test_in_place_transport_annotation_metadata_is_held(declared, monkeypatch):
    monkeypatch.setitem(declared.__annotations__, "foreign", object())
    with pytest.raises(RSILearningError, match="ready_state_invalid"):
        state._STATE_FUNCTIONS[1]()


@pytest.mark.parametrize("declared", [queued_reader._PENDING, queued_reader._READY])
def test_in_place_transport_field_identity_table_is_held(declared, monkeypatch):
    monkeypatch.setitem(declared.__dataclass_fields__, "foreign", object())
    with pytest.raises(RSILearningError, match="ready_state_invalid"):
        state._STATE_FUNCTIONS[1]()


@pytest.mark.parametrize("declared", [queued_reader._PENDING, queued_reader._READY])
@pytest.mark.parametrize("name,value", [
    ("name", "foreign"), ("type", object()), ("init", False),
    ("metadata", MappingProxyType({"foreign": object()})),
])
def test_transport_field_slot_metadata_is_held(declared, name, value, monkeypatch):
    field = next(iter(declared.__dataclass_fields__.values()))
    monkeypatch.setattr(field, name, value)
    with pytest.raises(RSILearningError, match="ready_state_invalid"):
        state._STATE_FUNCTIONS[1]()


@pytest.mark.parametrize("declared", [queued_reader._PENDING, queued_reader._READY])
def test_transport_dataclass_parameter_slots_are_held(declared, monkeypatch):
    parameters = declared.__dataclass_params__
    monkeypatch.setattr(parameters, "frozen", not parameters.frozen)
    with pytest.raises(RSILearningError, match="ready_state_invalid"):
        state._STATE_FUNCTIONS[1]()


def test_finite_state_graph_check_is_passive_and_has_no_transport_argument():
    assert state._STATE_FUNCTIONS[1]() is None
