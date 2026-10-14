"""Explicit child claims over inert bytes; no worker or evaluator is invoked."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_native_gateway import make_request
from test_rsi_python_controller_bridge import _ready

from lunar_evolution import RSILearningError
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_python_controller_bridge import (
    PythonProducerControllerBridgeError,
    claim_python_producer_controller_child,
    resolve_python_producer_controller_child_preview,
)
from lunar_evolution.rsi_store import RSILedger


def _preview(controller, request, memory, head):
    return resolve_python_producer_controller_child_preview(
        controller, run_id=controller.producer_sidecar.binding.run_id,
        episode_id=request.episode_id, request=request, memory=memory,
        expected_checkpoint_sha256=head,
    )


def _child_path(value, entry):
    return (value.root / "evolution" / "producer-batches" / entry["identity"]["journal_id"]
            / "python-producer-binding.json")


def _assert_only_claim(value, request, before, run_history, checkpoint_history):
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None
    assert value.ledger.history(value.binding.run_id) == run_history
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == checkpoint_history
    assert _inventory(value.root) == before
    with sqlite3.connect(value.ledger.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM rsi_native_episode_claims WHERE episode_id = ?",
            (request.episode_id,),
        ).fetchone() == (1,)


def test_child_claim_is_once_only_without_execution_or_checkpoint_budget_changes(tmp_path, monkeypatch):
    value, controller, head, _state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    before = _inventory(value.root)
    run_history = value.ledger.history(value.binding.run_id)
    checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
        claim = claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
        assert claim.status == "started"
        assert claim.request_sha256 == request.digest()
        assert claim.plan_sha256 == preview.plan.plan_sha256
        with pytest.raises(PythonProducerControllerBridgeError, match="episode_claim_exists"):
            claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
    _assert_only_claim(value, request, before, run_history, checkpoint_history)
    # The root gateway is unchanged, and recovery cannot stage or claim this child again.
    assert controller.gateway.producer_config.inputs.producer_sidecar.binding == value.sidecar.binding
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        controller.resume(value.binding.run_id)
    _assert_only_claim(value, request, before, run_history, checkpoint_history)


def test_child_claim_requires_the_original_controller_lock(tmp_path, monkeypatch):
    value, controller, head, _state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
    with pytest.raises(PythonProducerControllerBridgeError, match="controller_lock_required"):
        claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=preview.plan.plan_sha256) is None


@pytest.mark.parametrize("mutation", ["checkpoint", "request", "memory", "plan", "child", "broker"])
def test_child_claim_revalidates_preview_and_original_proofs(tmp_path, monkeypatch, mutation):
    value, controller, head, state, entry, request, memory = _ready(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
        if mutation == "checkpoint":
            changed = deepcopy(state)
            changed["observed_drift"] = True
            value.ledger.write_controller_checkpoint(value.binding.run_id, changed, expected_sha256=head)
        elif mutation == "request":
            request = replace(request, solver_settings=(("changed", True),))
        elif mutation == "memory":
            memory = replace(memory, snapshot_id="changed")
        elif mutation == "plan":
            preview = replace(preview, plan=replace(preview.plan, journal_id="changed", plan_sha256=None))
        elif mutation == "child":
            child_path = _child_path(value, entry)
            child_path.write_bytes(child_path.read_bytes() + b" ")
        else:
            preview.context.native_context.broker_config.headers["x-drift"] = "changed"
        before = _inventory(value.root)
        checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(PythonProducerControllerBridgeError):
            claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
        assert _inventory(value.root) == before
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == checkpoint_history
        assert value.ledger.inspect_native_episode_claim(
            request, plan_sha256=entry["ready"]["plan"]["plan_sha256"],
        ) is None


def test_checkpoint_changed_after_preview_is_rejected_inside_claim_transaction(tmp_path, monkeypatch):
    value, controller, head, state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    original = value.ledger.claim_native_episode

    def competing_checkpoint(req, **kwargs):
        changed = deepcopy(state)
        changed["observed_race"] = True
        value.ledger.write_controller_checkpoint(value.binding.run_id, changed, expected_sha256=head)
        return original(req, **kwargs)

    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
        monkeypatch.setattr(value.ledger, "claim_native_episode", competing_checkpoint)
        with pytest.raises(PythonProducerControllerBridgeError, match="claim_refused") as refused:
            claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
        assert str(refused.value.__cause__) == "rsi_native_episode_controller_checkpoint_conflict"
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=preview.plan.plan_sha256) is None
    assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["observed_race"] is True


def test_competing_native_claim_cannot_be_adopted_as_a_new_child_claim(tmp_path, monkeypatch):
    value, controller, head, _state, _entry, request, memory = _ready(tmp_path, monkeypatch)
    original = value.ledger.claim_native_episode
    competing = []

    def competing_claim(req, **kwargs):
        competing.append(original(req, plan_sha256=kwargs["plan_sha256"]))
        return original(req, **kwargs)

    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
        monkeypatch.setattr(value.ledger, "claim_native_episode", competing_claim)
        with pytest.raises(PythonProducerControllerBridgeError, match="claim_refused") as refused:
            claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
        assert str(refused.value.__cause__) == "rsi_native_episode_claim_exists"
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=preview.plan.plan_sha256,
    ) == competing[0]


@pytest.mark.parametrize("interruption", ["checkpoint", "interrupt", "sidecar"])
def test_post_claim_uncertainty_retains_started_claim_and_original_ready_proof(
    tmp_path, monkeypatch, interruption,
):
    value, controller, head, state, entry, request, memory = _ready(tmp_path, monkeypatch)
    original = value.ledger.claim_native_episode
    retained = []

    def interrupt_after_claim(req, **kwargs):
        retained.append(original(req, **kwargs))
        if interruption == "interrupt":
            raise KeyboardInterrupt("inert interruption after durable claim")
        if interruption == "checkpoint":
            changed = deepcopy(state)
            changed["postclaim_drift"] = True
            value.ledger.write_controller_checkpoint(value.binding.run_id, changed, expected_sha256=head)
        else:
            child = _child_path(value, entry)
            child.write_bytes(child.read_bytes() + b" ")
        return retained[0]

    with value.ledger.controller_lock(value.binding.run_id):
        preview = _preview(controller, request, memory, head)
        monkeypatch.setattr(value.ledger, "claim_native_episode", interrupt_after_claim)
        expected = KeyboardInterrupt if interruption == "interrupt" else PythonProducerControllerBridgeError
        with pytest.raises(expected):
            claim_python_producer_controller_child(controller, preview, request=request, memory=memory)
    assert value.ledger.inspect_native_episode_claim(
        request, plan_sha256=preview.plan.plan_sha256,
    ) == retained[0]
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with pytest.raises(RSILearningError):
        controller.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before


@pytest.mark.parametrize("missing", ["run", "checkpoint"])
def test_native_controller_claim_requires_paired_pins_before_sqlite(tmp_path, monkeypatch, missing):
    value, _controller, head, _state, entry, request, _memory = _ready(tmp_path, monkeypatch)
    pins = {"controller_run_id": value.binding.run_id, "expected_controller_checkpoint_sha256": head}
    pins.pop("controller_run_id" if missing == "run" else "expected_controller_checkpoint_sha256")
    monkeypatch.setattr(value.ledger, "_connect", lambda: pytest.fail("partial pins reached SQLite"))
    with pytest.raises(RSILearningError, match="controller_pins_invalid"):
        value.ledger.claim_native_episode(request, plan_sha256=entry["ready"]["plan"]["plan_sha256"], **pins)


def test_reopened_ledger_cannot_borrow_another_instance_controller_lock(tmp_path, monkeypatch):
    value, _controller, head, _state, entry, request, _memory = _ready(tmp_path, monkeypatch)
    foreign = RSILedger(value.ledger.database)
    with value.ledger.controller_lock(value.binding.run_id), pytest.raises(
        RSILearningError, match="controller_lock_required",
    ):
        foreign.claim_native_episode(
            request, plan_sha256=entry["ready"]["plan"]["plan_sha256"],
            controller_run_id=value.binding.run_id, expected_controller_checkpoint_sha256=head,
        )


def test_guarded_store_claim_rejects_terminal_replay_without_changing_legacy_api(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    request = make_request()
    plan_sha256 = "a" * 64
    claim = ledger.claim_native_episode(request, plan_sha256=plan_sha256)
    result = SolverResult(
        request.episode_id, request.digest(), "cancelled", None, None, None, "b" * 64,
        terminal_reason="provider-free terminal claim fixture",
    )
    terminal = ledger.publish_native_episode_result(
        request, plan_sha256=plan_sha256, result=result, expected_claim=claim,
    )
    # Original native terminal replay remains idempotent.
    assert ledger.claim_native_episode(request, plan_sha256=plan_sha256) == terminal
    with ledger.controller_lock("claim-controller"):
        head = ledger.write_controller_checkpoint(
            "claim-controller", {"run_id": "claim-controller"}, expected_sha256=None,
        )
        history = ledger.controller_checkpoint_history("claim-controller")
        with pytest.raises(RSILearningError, match="claim_exists"):
            ledger.claim_native_episode(
                request, plan_sha256=plan_sha256, controller_run_id="claim-controller",
                expected_controller_checkpoint_sha256=head,
            )
        assert ledger.controller_checkpoint_history("claim-controller") == history
    assert ledger.inspect_native_episode_claim(request, plan_sha256=plan_sha256) == terminal


def test_guarded_store_claim_cannot_create_against_a_missing_checkpoint(tmp_path):
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    request = make_request()
    with ledger.controller_lock("claim-controller"), pytest.raises(
        RSILearningError, match="controller_checkpoint_conflict",
    ):
        ledger.claim_native_episode(
            request, plan_sha256="a" * 64, controller_run_id="claim-controller",
            expected_controller_checkpoint_sha256="b" * 64,
        )
    assert ledger.inspect_native_episode_claim(request, plan_sha256="a" * 64) is None
