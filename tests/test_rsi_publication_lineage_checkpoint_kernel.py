"""Pure lineage deltas and original DRS CAS failures; no producer processes."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from pathlib import Path

import pytest
from test_rsi_publication_lineage_owner import _captured_owner

from lunar_evolution import rsi_publication_lineage as lineage
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_publication_lineage import (
    _publication_lineage_checkpoint_delta,
    _validate_publication_lineage_checkpoint_readback,
)

_REBOUND_HELPER_CALLS = []


def _unexpected_rebound_helper(*_args, **_kwargs):
    _REBOUND_HELPER_CALLS.append(True)
    raise AssertionError("rebound checkpoint helper must not execute")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("checkpoint kernel fixture must not execute a process or connect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def kernel_workspace(tmp_path_factory):
    # Paths are part of the retained binding. Keep macOS temp prefixes within its existing cap.
    return tmp_path_factory.mktemp("k")


def test_delta_preserves_original_fields_and_json_values_without_mutating_capture():
    captured = canonical_json({
        "mode": "drs", "run_id": "original", "unicode": "月球🌙",
        "values": [None, True, False, 9007199254740993, -0.0, 1.25, {"v": ["x"]}],
        "python_admission_refs": {"episode": {"record_sha256": "a" * 64}},
        "producer_publication_lineage": {"before": "retained"},
    })
    wire = {"batches": [], "head": None, "rejections": []}
    expected = _publication_lineage_checkpoint_delta(captured, wire)
    original = json.loads(captured)
    assert original["producer_publication_lineage"] == {"before": "retained"}
    assert {key: value for key, value in expected.items() if key != "producer_publication_lineage"} == {
        key: value for key, value in original.items() if key != "producer_publication_lineage"
    }
    assert canonical_json(expected) == canonical_json(original | {"producer_publication_lineage": wire})
    assert wire == {"batches": [], "head": None, "rejections": []}
    assert canonical_json(json.loads(captured)) == captured


def test_delta_retains_the_112_kib_checkpoint_limit():
    # A payload allowed by the larger controller serializer must not widen lineage capacity.
    captured = canonical_json({"retained": "x" * (112 * 1024)}, maximum=8 * 1024 * 1024)
    with pytest.raises(RSILearningError, match="^rsi_publication_lineage_capacity_exceeded$"):
        _publication_lineage_checkpoint_delta(captured, {"batches": []})


@pytest.mark.parametrize(("head", "payload"), [
    (None, None), ("b" * 64, b"{}"), ("a" * 64, None), ("a" * 64, b'{"changed":true}'),
])
def test_readback_requires_both_original_returned_head_and_exact_canonical_bytes(head, payload):
    with pytest.raises(RSILearningError, match="^rsi_publication_lineage_acknowledgement_readback_invalid$"):
        _validate_publication_lineage_checkpoint_readback(
            expected_head="a" * 64, expected_payload=b"{}", observed_head=head, observed_payload=payload,
        )
    _validate_publication_lineage_checkpoint_readback(
        expected_head="a" * 64, expected_payload=b"{}", observed_head="a" * 64, observed_payload=b"{}",
    )


def _capture(owner):
    return owner._context, owner._head, owner._payload, json.loads(owner._payload)


def _assert_stale_and_poisoned(owner, before):
    context, head, payload, state = before
    assert owner._context is context
    assert owner._head == head and owner._payload == payload
    assert owner._context.state == state
    assert owner._poisoned is True and owner._pending_wire is None


def test_original_drs_owner_uses_one_captured_head_cas_and_only_lineage_delta(kernel_workspace, monkeypatch):
    def operation(owner, controller, value):
        before = _capture(owner)
        wire = owner._wire(owner._context.state)
        expected = before[3] | {"producer_publication_lineage": wire}
        write = value.ledger.write_controller_checkpoint
        calls = []

        def observed_write(run_id, state, *, expected_sha256):
            assert value.ledger.controller_lock_held(run_id)
            assert getattr(value.ledger._observation_scope, "depth", 0) == 0
            calls.append((run_id, canonical_json(state, maximum=8 * 1024 * 1024), expected_sha256))
            return write(run_id, state, expected_sha256=expected_sha256)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed_write)
        owner._ack(wire)
        assert calls == [(owner._run_id, controller._python_admission_flow_payload(expected), before[1])]
        assert owner._head != before[1] and owner._context is not before[0]
        assert owner._payload == controller._python_admission_flow_payload(expected)
        assert owner._context.state == expected
        assert value.ledger.controller_checkpoint(owner._run_id) == (owner._head, expected)
        assert owner._poisoned is False and owner._pending_wire is None

    _captured_owner(kernel_workspace, monkeypatch, operation)


def test_actual_competing_cas_does_not_refresh_or_retry_original_owner(kernel_workspace, monkeypatch):
    def operation(owner, _controller, value):
        before = _capture(owner)
        write = value.ledger.write_controller_checkpoint
        calls = []

        def competing_write(run_id, state, *, expected_sha256):
            calls.append(expected_sha256)
            foreign = before[3] | {"foreign_increment": True}
            write(run_id, foreign, expected_sha256=expected_sha256)
            return write(run_id, state, expected_sha256=expected_sha256)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", competing_write)
        wire = owner._wire(owner._context.state)
        with pytest.raises(RSILearningError, match="^rsi_controller_checkpoint_conflict$"):
            owner._ack(wire)
        _assert_stale_and_poisoned(owner, before)
        durable_head, durable = value.ledger.controller_checkpoint(owner._run_id)
        assert durable_head != before[1]
        assert durable == before[3] | {"foreign_increment": True}
        with pytest.raises(RSILearningError, match="owner_drift"):
            owner._ack(wire)
        assert calls == [before[1]]

    _captured_owner(kernel_workspace, monkeypatch, operation)


@pytest.mark.parametrize("fault", ["missing", "wrong-head", "wrong-payload"])
def test_durable_write_with_failed_readback_keeps_original_capture(kernel_workspace, monkeypatch, fault):
    def operation(owner, controller, value):
        before = _capture(owner)
        write = value.ledger.write_controller_checkpoint
        checkpoint = value.ledger.controller_checkpoint
        committed = []
        invalid_state = object()
        serialized_invalid = []
        serialize = controller._python_admission_flow_payload

        def observed_write(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            committed.append((head, json.loads(canonical_json(state, maximum=8 * 1024 * 1024))))
            return head

        def failed_readback(run_id):
            if not committed:
                return checkpoint(run_id)
            if fault == "missing":
                return None
            if fault == "wrong-head":
                return "f" * 64, invalid_state
            return committed[0][0], {"changed": True}

        def observed_serialize(state):
            if state is invalid_state:
                serialized_invalid.append(True)
                pytest.fail("wrong-head readback serialized its untrusted state")
            return serialize(state)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed_write)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", failed_readback)
        monkeypatch.setattr(controller, "_python_admission_flow_payload", observed_serialize)
        wire = owner._wire(owner._context.state)
        with pytest.raises(RSILearningError, match="^rsi_publication_lineage_acknowledgement_readback_invalid$"):
            owner._ack(wire)
        _assert_stale_and_poisoned(owner, before)
        assert serialized_invalid == [] and len(committed) == 1
        assert checkpoint(owner._run_id) == committed[0]
        assert committed[0][1] == before[3] | {"producer_publication_lineage": wire}
        with pytest.raises(RSILearningError, match="owner_drift"):
            owner._ack(wire)
        assert len(committed) == 1

    _captured_owner(kernel_workspace, monkeypatch, operation)


@pytest.mark.parametrize("gate", ["context", "root-binding"])
def test_post_readback_owner_gate_failure_cannot_acknowledge_durable_delta(kernel_workspace, monkeypatch, gate):
    def operation(owner, controller, value):
        before = _capture(owner)
        write = value.ledger.write_controller_checkpoint
        committed = []

        def observed_write(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            committed.append(head)
            return head

        attribute = ("_python_admission_assert_flow_context" if gate == "context"
                     else "_validate_original_run_checkpoint_producer_binding")
        original_gate = getattr(controller, attribute)

        def refuse_after_readback(*args, **kwargs):
            if committed:
                assert getattr(value.ledger._observation_scope, "depth", 0) > 0
                raise RSILearningError("fixture_original_owner_gate_failed")
            return original_gate(*args, **kwargs)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed_write)
        monkeypatch.setattr(controller, attribute, refuse_after_readback)
        wire = owner._wire(owner._context.state)
        with pytest.raises(RSILearningError, match="^fixture_original_owner_gate_failed$"):
            owner._ack(wire)
        _assert_stale_and_poisoned(owner, before)
        assert len(committed) == 1
        assert value.ledger.controller_checkpoint(owner._run_id) == (
            committed[0], before[3] | {"producer_publication_lineage": wire},
        )

    _captured_owner(kernel_workspace, monkeypatch, operation)


@pytest.mark.parametrize("helper", [
    "_publication_lineage_checkpoint_delta", "_validate_publication_lineage_checkpoint_readback",
])
def test_live_helper_rebind_refuses_original_owner_before_helper_or_cas(kernel_workspace, monkeypatch, helper):
    def operation(owner, _controller, value):
        before = _capture(owner)
        original_policy = owner._policy
        original_source = hashlib.sha256(Path(lineage.__file__).read_bytes()).hexdigest()
        with value.ledger.read_only_observations():
            history = value.ledger.controller_checkpoint_history(owner._run_id)
        writes = []

        def forbidden_write(*_args, **_kwargs):
            writes.append(True)
            pytest.fail("live helper drift reached checkpoint CAS")

        _REBOUND_HELPER_CALLS.clear()
        wire = owner._wire(owner._context.state)
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", forbidden_write)
        with monkeypatch.context() as changed:
            changed.setattr(lineage, helper, _unexpected_rebound_helper)
            with pytest.raises(RSILearningError, match="^rsi_publication_lineage_policy_drift$"):
                owner._ack(wire)
        assert _REBOUND_HELPER_CALLS == [] and writes == []
        assert owner._context is before[0] and owner._head == before[1] and owner._payload == before[2]
        assert owner._context.state == before[3] and owner._policy == original_policy
        assert owner._poisoned is False and owner._pending_wire is None
        assert hashlib.sha256(Path(lineage.__file__).read_bytes()).hexdigest() == original_source
        with value.ledger.read_only_observations():
            assert value.ledger.controller_checkpoint_history(owner._run_id) == history

    _captured_owner(kernel_workspace, monkeypatch, operation)
