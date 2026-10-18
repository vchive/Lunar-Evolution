"""Original reservation recovery uses real controller journal writes, without work."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_brs_reserved_wave import _fixture

from lunar_evolution import RSILearningController, fixture_solver_gateway
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_reserved_reservation import read_reserved_brs_reservation
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSIExecutionConfig, NativeRSISolverGateway
from lunar_evolution.rsi_store import RSILedger


def _setup(tmp_path, *, count=2, reserve=None):
    expected, _state, _options = _fixture(count)
    ledger = RSILedger(tmp_path / "original.sqlite3")
    controller = RSILearningController(fixture_solver_gateway("mock"), ledger=ledger)
    run_id, plan, pins = expected["run_id"], expected["plan"], expected["pins"]
    budget = expected["budget_state"]["planned"]
    with ledger.controller_lock(run_id):
        record = controller._start_run(run_id=run_id, mode="brs", plan=plan, budget=budget, **pins)
        state = controller._flow_state(record, run_id=run_id, plan=plan, pins=pins, budget=budget)
        controller._save_flow(record, state)
        history = [ledger.controller_checkpoint(run_id)]
        for intent in list(expected["intents"].values())[:count if reserve is None else reserve]:
            controller._prepare_intent(record, state, PracticeEpisode.from_dict(intent["episode"]),
                                       SolverRequest.from_dict(intent["request"]))
            history.append(ledger.controller_checkpoint(run_id))
    return controller, tuple(expected["intents"]), state, history


def _read(controller, ids, head):
    return read_reserved_brs_reservation(controller.ledger, run_id="reserved-brs", episode_ids=ids,
                                         expected_checkpoint_sha256=head)


def test_original_complete_reservation_is_derived_from_natural_checkpoint_history(tmp_path):
    controller, ids, state, history = _setup(tmp_path)
    original_head = history[-1][0]
    later = deepcopy(state)
    later.update(phase="selected", current_episode_id=ids[0])
    with controller.ledger.controller_lock("reserved-brs"):
        latest = controller.ledger.write_controller_checkpoint("reserved-brs", later,
                                                               expected_sha256=original_head)
        observed = _read(controller, ids, latest)
    assert observed.original_checkpoint_sha256 == original_head != latest
    assert observed.ledger.checkpoint_sha256 == latest
    assert observed.original_state() == state
    assert observed.original_state_sha256 != original_head
    assert observed.original_state_bytes == canonical_json(state, maximum=128 * 1024)
    # Returned mutable copies cannot refresh either captured head or baseline.
    observed.original_state()["intents"].clear()
    assert len(observed.original_state()["intents"]) == len(ids)
    assert controller.ledger.controller_checkpoint("reserved-brs") == (latest, later)


@pytest.mark.parametrize("count", [1, 8])
def test_original_reservation_keeps_exact_deadline_and_n_counters(tmp_path, count):
    controller, ids, state, history = _setup(tmp_path, count=count)
    with controller.ledger.controller_lock("reserved-brs"):
        observed = _read(controller, ids, history[-1][0])
    assert observed.original_state()["budget_state"] == state["budget_state"]
    assert observed.original_state()["budget_state"]["planned"]["deadline_unix"] == 4_000_000_000.125


def test_partial_reservation_requires_existing_intent_reuse_before_observation(tmp_path):
    controller, ids, _state, history = _setup(tmp_path, reserve=1)
    # Whole-domain reader also refuses a partial current domain. It cannot invent
    # the missing intent or charge it on behalf of the serial continuation.
    with controller.ledger.controller_lock("reserved-brs"), pytest.raises(RSILearningError):
        _read(controller, ids, history[-1][0])
    assert controller.ledger.controller_checkpoint("reserved-brs") == history[-1]


@pytest.mark.parametrize("fault", ["refund", "recharge", "deadline", "memory", "policy", "intent"])
def test_later_checkpoint_cannot_be_adopted_as_a_new_reservation(tmp_path, fault):
    controller, ids, state, history = _setup(tmp_path)
    changed = deepcopy(state)
    if fault in {"refund", "recharge"}:
        changed["budget_state"]["consumed"]["solver_invocations"] += -1 if fault == "refund" else 1
        if fault == "recharge":
            changed["budget_state"]["planned"]["max_solver_invocations"] += 1
        else:
            changed["budget_state"]["remaining"]["solver_invocations"] += 1
    elif fault == "deadline":
        changed["budget_state"]["planned"]["deadline_unix"] += 100
    elif fault == "memory":
        changed["root_snapshot"]["parent_snapshot_sha256"] = "a" * 64
    elif fault == "policy":
        changed["producer_brs_checkpoint_policy"] = {"new": "later baseline"}
    else:
        changed["intents"][ids[0]]["episode"]["parent_target_episode_id"] = "changed-parent"
    with controller.ledger.controller_lock("reserved-brs"):
        head = controller.ledger.write_controller_checkpoint("reserved-brs", changed,
                                                             expected_sha256=history[-1][0])
        with pytest.raises(RSILearningError, match="reserved_reservation_"):
            _read(controller, ids, head)
    assert controller.ledger.controller_checkpoint("reserved-brs") == (head, changed)


def test_no_initial_empty_checkpoint_cannot_manufacture_an_original_baseline(tmp_path):
    controller, ids, state, history = _setup(tmp_path)
    # Simulate a valid-hash alternate journal whose first root already has all
    # reservations. The original run row retains the real zero-consumption state.
    from lunar_evolution.rsi_brs_reserved_ledger import _read_reserved_rows
    assert _read_reserved_rows(str(controller.ledger.database), run_id="reserved-brs", episode_ids=ids)
    connection = controller.ledger._connect()
    try:
        connection.execute("DELETE FROM rsi_controller_journal WHERE run_id = ?", ("reserved-brs",))
        connection.commit()
    finally:
        connection.close()
    with controller.ledger.controller_lock("reserved-brs"):
        head = controller.ledger.write_controller_checkpoint("reserved-brs", state, expected_sha256=None)
        with pytest.raises(RSILearningError, match="run_origin_drift|reservation_order_drift"):
            _read(controller, ids, head)
    assert head != history[-1][0]


def test_claim_before_owner_fence_is_retained_while_reading_original_reservation(tmp_path):
    from test_rsi_brs_reserved_ledger import _plan
    controller, ids, state, history = _setup(tmp_path)
    request = SolverRequest.from_dict(state["intents"][ids[1]]["request"])
    calls = []

    def plan(request, memory):
        return replace(_plan(request, memory), run_id="reserved-brs", plan_sha256=None)

    def interrupted(request, plan):
        calls.append(request.episode_id)
        raise RuntimeError("inert interruption before preparation")

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(controller.ledger, plan, interrupted))
    with pytest.raises(RSILearningError):
        gateway.run(request, controller.snapshot)
    with controller.ledger.controller_lock("reserved-brs"):
        observed = _read(controller, ids, history[-1][0])
    assert observed.ledger.ledger_traces()[ids[1]]["claim"]["status"] == "started"
    assert observed.ledger.ledger_traces()[ids[1]]["obligation_sha256"] is None
    assert observed.original_state()["executions"] == {}
    assert observed.original_state()["budget_state"] == state["budget_state"]
    assert calls == [ids[1]]


def test_no_nested_lease_or_writes_during_reservation_observation(tmp_path, monkeypatch):
    controller, ids, _state, history = _setup(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only reservation observer mutated or reacquired a lease")

    with controller.ledger.controller_lock("reserved-brs"):
        for name in ("controller_lock", "write_controller_checkpoint", "claim_native_episode",
                     "publish_native_episode_result"):
            monkeypatch.setattr(RSILedger, name, forbidden)
        observed = _read(controller, ids, history[-1][0])
    assert observed.original_checkpoint_sha256 == history[-1][0]


def test_history_must_not_hide_an_extra_retry_charge_in_original_reservation(tmp_path):
    controller, ids, state, history = _setup(tmp_path)
    changed = deepcopy(state)
    changed["budget_state"]["consumed"]["unknown_retries"] = 1
    with controller.ledger.controller_lock("reserved-brs"):
        head = controller.ledger.write_controller_checkpoint("reserved-brs", changed,
                                                             expected_sha256=history[-1][0])
        with pytest.raises(RSILearningError):
            _read(controller, ids, head)


@pytest.mark.parametrize("fault", ["policy", "depth", "reservation_rollback", "early_execution"])
def test_restoring_latest_state_cannot_erase_an_intermediate_history_conflict(tmp_path, fault):
    controller, ids, state, history = _setup(tmp_path, reserve=1 if fault == "early_execution" else None)
    changed = deepcopy(state)
    if fault == "policy":
        changed["producer_staging_policy"] = {"replacement": True}
    elif fault == "depth":
        changed["budget_state"]["planned"]["max_depth"] = 100
    elif fault == "reservation_rollback":
        changed = deepcopy(history[-2][1])
    else:
        changed["executions"][ids[0]] = {"premature": True}
    with controller.ledger.controller_lock("reserved-brs"):
        head = controller.ledger.write_controller_checkpoint("reserved-brs", changed,
                                                             expected_sha256=history[-1][0])
        restored = deepcopy(state)
        if fault == "early_execution":
            # Finish the original missing reservation with its genuine controller
            # request shape; retain the earlier premature execution in history.
            full, _state, _options = _fixture(2)
            restored = full
        latest = controller.ledger.write_controller_checkpoint("reserved-brs", restored,
                                                               expected_sha256=head)
        with pytest.raises(RSILearningError, match="reserved_reservation_"):
            _read(controller, ids, latest)
    assert controller.ledger.controller_checkpoint("reserved-brs") == (latest, restored)


@pytest.mark.parametrize("value", [False, None, [], 0, ""])
def test_falsey_nonmapping_execution_history_is_not_an_empty_pre_dispatch_state(tmp_path, value):
    controller, ids, state, history = _setup(tmp_path, reserve=1)
    changed = deepcopy(state)
    changed["executions"] = value
    full, _state, _options = _fixture(2)
    with controller.ledger.controller_lock("reserved-brs"):
        head = controller.ledger.write_controller_checkpoint("reserved-brs", changed,
                                                             expected_sha256=history[-1][0])
        latest = controller.ledger.write_controller_checkpoint("reserved-brs", full,
                                                               expected_sha256=head)
        with pytest.raises(RSILearningError, match="attempt_shape_invalid"):
            _read(controller, ids, latest)
    assert controller.ledger.controller_checkpoint("reserved-brs") == (latest, full)
