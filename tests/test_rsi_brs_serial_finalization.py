"""Actual controller memory writes; these tests do not claim native acceptance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_brs_reserved_reservation import _setup
from test_rsi_brs_reserved_wave import _fixture

from lunar_evolution.rsi_brs_serial_finalization import validate_reserved_brs_finalization_history
from lunar_evolution.rsi_gateway import RSIMemoryStore
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError


def _complete(tmp_path, outcomes):
    controller, domain, state, _history = _setup(tmp_path, count=len(outcomes))
    _original, completed, _options = _fixture(len(outcomes), outcomes)
    state["executions"] = completed["executions"]
    # The projection fixture intentionally omits promotion pins. This suite
    # exercises real memory publication, so retain a fully pinned verifier.
    for key, execution in state["executions"].items():
        if execution["result"]["status"] == "completed":
            parsed = controller._deserialize_execution(execution)
            verifier = replace(parsed.verifier, **{name: getattr(parsed.episode, name) for name in (
                "contract_sha256", "evaluator_sha256", "environment_sha256",
                "official_evaluation_receipt_sha256")})
            state["executions"][key] = controller._serialize_execution(replace(
                parsed, verifier=verifier, episode=replace(parsed.episode, verifier=verifier)))
    state.update(phase="evaluated", current_episode_id=domain[-1])
    record = controller.ledger.get_run(state["run_id"])
    with controller.ledger.controller_lock(state["run_id"]):
        controller._save_flow(record, state)
    return controller, domain, record, state


def _validate(controller, domain, record):
    history = controller.ledger.controller_checkpoint_history(record.logical_id)
    before = deepcopy(history)
    result = validate_reserved_brs_finalization_history(controller, record, history, domain)
    assert controller.ledger.controller_checkpoint_history(record.logical_id) == before
    return result


@pytest.mark.parametrize("outcomes", [
    ("all_rejected", "all_rejected"), ("published", "all_rejected"),
    ("all_rejected", "published"), ("published", "published"),
    ("published", "all_rejected", "published"),
])
def test_plan_order_memory_finalization_keeps_original_executions_and_m0(tmp_path, outcomes):
    controller, domain, record, state = _complete(tmp_path, outcomes)
    scheduling = _validate(controller, domain, record)
    frozen = MemorySnapshot.from_dict(state["root_snapshot"]).digest()
    with controller.ledger.controller_lock(record.logical_id):
        for key, wire in zip(domain, state["plan"]["practices"], strict=True):
            controller._commit_flow(record, state, controller._deserialize_execution(state["executions"][key]),
                                    controller._decision_from_dict(wire), frozen_parent=frozen)
            assert _validate(controller, domain, record) == scheduling
        controller._finish_flow(record, state, "completed")
    assert _validate(controller, domain, record) == scheduling
    assert state["root_snapshot"] == scheduling["root_snapshot"]
    assert state["executions"] == scheduling["executions"]
    assert state["budget_state"] == scheduling["budget_state"]
    assert tuple(item.episode_id for item in controller.snapshot.items) == tuple(
        key for key, outcome in zip(domain, outcomes, strict=True) if outcome == "published")


def test_commit_crash_after_memory_record_reopens_exact_snapshot_once(tmp_path, monkeypatch):
    controller, domain, record, state = _complete(tmp_path, ("published", "all_rejected"))
    key = domain[0]
    original_save = controller._save_flow

    def fail_after_memory(record, body, **kwargs):
        if body["phase"] == "committed":
            raise RuntimeError("inert crash after immutable memory publication")
        return original_save(record, body, **kwargs)

    monkeypatch.setattr(controller, "_save_flow", fail_after_memory)
    with controller.ledger.controller_lock(record.logical_id), pytest.raises(RuntimeError, match="inert crash"):
        controller._commit_flow(record, state, controller._deserialize_execution(state["executions"][key]),
            controller._decision_from_dict(state["plan"]["practices"][0]),
            frozen_parent=MemorySnapshot.from_dict(state["root_snapshot"]).digest())
    saved = controller.ledger.get("memory:snapshot-memory-" + key)
    assert saved is not None
    _validate(controller, domain, record)
    # Restore only the original durable effective memory. _commit reopens its
    # existing exact immutable record instead of appending a second memory item.
    state = controller.ledger.controller_checkpoint(record.logical_id)[1]
    controller.memory_store = RSIMemoryStore(MemorySnapshot.from_dict(state["memory_snapshot"]))
    monkeypatch.setattr(controller, "_save_flow", original_save)
    with controller.ledger.controller_lock(record.logical_id):
        controller._commit_flow(record, state, controller._deserialize_execution(state["executions"][key]),
            controller._decision_from_dict(state["plan"]["practices"][0]),
            frozen_parent=MemorySnapshot.from_dict(state["root_snapshot"]).digest())
    _validate(controller, domain, record)
    assert controller.ledger.get("memory:snapshot-memory-" + key) == saved
    assert len(controller.snapshot.items) == 1


@pytest.mark.parametrize("fault", ["budget", "execution", "lineage", "memory", "skip", "failed-source",
                                   "committed-without-memory", "early-terminal", "unknown", "reopen"])
def test_finalization_drift_never_grants_another_commit(tmp_path, fault):
    controller, domain, record, state = _complete(tmp_path, ("published", "published", "all_rejected"))
    body = deepcopy(state)
    body.update(phase="commit", current_episode_id=domain[0])
    if fault == "budget":
        body["budget_state"]["consumed"]["solver_invocations"] += 1
    elif fault == "execution":
        body["executions"][domain[0]]["result"]["trace_digest"] = "b" * 64
    elif fault == "lineage":
        body["producer_publication_lineage"] = {"forged": True}
    elif fault == "memory":
        body["memory_snapshot"]["snapshot_id"] = "foreign"
    elif fault == "skip":
        body["current_episode_id"] = domain[1]
    elif fault == "failed-source":
        body["current_episode_id"] = domain[2]
    elif fault == "committed-without-memory":
        body["phase"] = "committed"
    elif fault == "early-terminal":
        body.update(phase="terminal", status="completed", current_episode_id=domain[-1])
    elif fault == "unknown":
        body["status"] = "unknown"
    else:
        terminal = deepcopy(state)
        terminal.update(phase="terminal", status="completed")
        # A false terminal followed by reopening is independently rejected even
        # before a real memory publication is considered.
        with controller.ledger.controller_lock(record.logical_id):
            controller.ledger.write_controller_checkpoint(record.logical_id, terminal,
                expected_sha256=controller.ledger.controller_checkpoint(record.logical_id)[0])
    with controller.ledger.controller_lock(record.logical_id):
        controller.ledger.write_controller_checkpoint(record.logical_id, body,
            expected_sha256=controller.ledger.controller_checkpoint(record.logical_id)[0])
    before = controller.ledger.controller_checkpoint_history(record.logical_id)
    with pytest.raises(RSILearningError, match="rsi_brs_reserved_finalization_"):
        _validate(controller, domain, record)
    assert controller.ledger.controller_checkpoint_history(record.logical_id) == before
    assert controller.snapshot.items == ()
