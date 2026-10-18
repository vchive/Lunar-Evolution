"""Real SQLite/natural gateway observations without producers or evaluators."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_native_gateway import bundle, plan_factory

from lunar_evolution.rsi_brs_reconcile import FIELD, BRSReconcileObligation
from lunar_evolution.rsi_brs_rejection_ready_ledger import read_rejection_ready_rows
from lunar_evolution.rsi_brs_reserved_ledger import (
    assert_reserved_brs_ledger,
    read_reserved_brs_ledger,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSIExecutionConfig, NativeRSISolverGateway
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


def _setup(tmp_path, count=2):
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    run_id = "reserved"
    ids = tuple(f"{run_id}-practice-0-{index}" for index in range(count))
    requests = tuple(SolverRequest.build(
        episode_id=key, contract_sha256=HEX, evaluator_sha256=HEX, environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(), solver_id="fixture",
    ) for key in ids)
    state = {"run_id": run_id, "mode": "brs", "plan": {
        "mode": "brs", "wave": 0, "practices": [{} for _ in ids],
    }, "intents": {key: {"request": request.to_dict()} for key, request in zip(ids, requests)},
        "executions": {}}
    record = ledger.create_run(run_id, HEX, state)
    ledger.transition(run_id, state="running", expected_record_sha256=record.record_sha256)
    with ledger.controller_lock(run_id):
        head = ledger.write_controller_checkpoint(run_id, state, expected_sha256=None)
    return ledger, ids, requests, state, head


def _read(ledger, ids, head):
    return read_reserved_brs_ledger(
        ledger, run_id="reserved", episode_ids=ids, expected_checkpoint_sha256=head,
    )


def _plan(request, memory):
    return replace(plan_factory(request, memory), run_id="reserved", task_id=request.episode_id,
                   journal_id=request.episode_id + "-journal", plan_sha256=None)


def test_whole_original_domain_read_is_immutable_and_leaves_six_tables_unchanged(tmp_path):
    ledger, ids, _requests, state, head = _setup(tmp_path)
    before = read_rejection_ready_rows(str(ledger.database), run_id="reserved", episode_ids=ids)
    with ledger.controller_lock("reserved"):
        observation = _read(ledger, ids, head)
    assert observation.checkpoint_sha256 == head
    assert observation.episode_ids == ids
    assert all(trace["claim"] is trace["episode"] is trace["result"] is None
               for trace in observation.ledger_traces().values())
    changed = observation.ledger_traces()
    changed[ids[0]]["claim"] = "caller modification"
    assert observation.ledger_traces()[ids[0]]["claim"] is None
    assert ledger.controller_checkpoint("reserved") == (head, state)
    assert read_rejection_ready_rows(str(ledger.database), run_id="reserved", episode_ids=ids) == before


@pytest.mark.parametrize("ordinal", [0, 1])
def test_natural_gateway_claim_before_any_fence_is_visible_across_whole_domain(tmp_path, ordinal):
    ledger, ids, requests, state, head = _setup(tmp_path)
    calls = []

    def interrupted_provider(request, plan):
        calls.append(request.episode_id)
        assert ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256).status == "started"
        raise RuntimeError("inert interruption before owner mailbox")

    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, _plan, interrupted_provider))
    with pytest.raises(RSILearningError):
        gateway.run(requests[ordinal], EMPTY_MEMORY_SNAPSHOT)
    assert FIELD not in state
    with ledger.controller_lock("reserved"):
        observation = _read(ledger, ids, head)
    traces = observation.ledger_traces()
    assert traces[ids[ordinal]]["claim"]["status"] == "started"
    assert traces[ids[ordinal]]["episode"] is traces[ids[ordinal]]["result"] is None
    assert traces[ids[ordinal]]["obligation_sha256"] is None
    assert traces[ids[1 - ordinal]]["claim"] is None
    assert calls == [ids[ordinal]]
    # Reading never acquires another claim or retries the interrupted callback.
    assert ledger.controller_checkpoint("reserved") == (head, state)


def test_reader_requires_the_original_lease_before_database_observation(tmp_path, monkeypatch):
    ledger, ids, _requests, _state, head = _setup(tmp_path)
    import lunar_evolution.rsi_brs_reserved_ledger as module

    def forbidden(*args, **kwargs):
        pytest.fail("read occurred before held lease check")

    monkeypatch.setattr(module, "_read_reserved_rows", forbidden)
    with pytest.raises(RSILearningError, match="controller_lock_required"):
        _read(ledger, ids, head)


@pytest.mark.parametrize("fault", ["omitted_child", "reordered", "foreign", "stale_head"])
def test_partial_foreign_or_stale_domain_never_looks_untouched(tmp_path, fault):
    ledger, ids, _requests, _state, head = _setup(tmp_path)
    selected, selected_head = ids, head
    if fault == "omitted_child":
        selected = ids[:1]
    elif fault == "reordered":
        selected = tuple(reversed(ids))
    elif fault == "foreign":
        selected = (ids[0], "foreign")
    else:
        selected_head = HEX
    with ledger.controller_lock("reserved"), pytest.raises(RSILearningError, match="reserved_ledger_"):
        _read(ledger, selected, selected_head)


def test_removed_current_fence_does_not_erase_historical_attempt_trace(tmp_path):
    ledger, ids, requests, state, head = _setup(tmp_path)
    obligation = BRSReconcileObligation(
        "reserved", ids[0], "selected", HEX, requests[0].digest(), HEX, head, HEX,
    )
    with ledger.controller_lock("reserved"):
        previous = deepcopy(state)
        previous[FIELD] = {ids[0]: obligation.to_dict()}
        fenced = ledger.write_controller_checkpoint("reserved", previous, expected_sha256=head)
        latest = ledger.write_controller_checkpoint("reserved", state, expected_sha256=fenced)
        observed = _read(ledger, ids, latest)
    trace = observed.ledger_traces()[ids[0]]
    assert trace["obligation_sha256"] is None
    assert trace["historical_obligation_sha256s"] == [obligation.digest()]


def test_same_content_database_replacement_cannot_refresh_original_inode(tmp_path, monkeypatch):
    ledger, ids, _requests, _state, head = _setup(tmp_path)
    import lunar_evolution.rsi_brs_reserved_ledger as module
    original = module._read_reserved_rows

    def replaced(*args, **kwargs):
        observed = original(*args, **kwargs)
        # A real SQLite backup preserves logical rows while replacing the named inode.
        import sqlite3

        replacement = ledger.database.with_suffix(".replacement")
        with sqlite3.connect(ledger.database) as source, sqlite3.connect(replacement) as destination:
            source.backup(destination)
        ledger.database.rename(ledger.database.with_suffix(".old"))
        replacement.rename(ledger.database)
        return observed

    monkeypatch.setattr(module, "_read_reserved_rows", replaced)
    with ledger.controller_lock("reserved"), pytest.raises(RSILearningError, match="ledger_identity_drift"):
        _read(ledger, ids, head)


def test_natural_gateway_terminal_result_is_observed_without_root_settlement(tmp_path):
    ledger, ids, requests, state, head = _setup(tmp_path)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, _plan, bundle))
    result = gateway.run(requests[0], EMPTY_MEMORY_SNAPSHOT)
    with ledger.controller_lock("reserved"):
        observation = _read(ledger, ids, head)
    assert observation.ledger_traces()[ids[0]]["result"] == result.to_dict()
    assert observation.ledger_traces()[ids[0]]["claim"]["status"] == "completed"
    assert ledger.controller_checkpoint("reserved") == (head, state)


def test_root_change_during_semantic_observation_refuses_without_adopting_it(tmp_path, monkeypatch):
    ledger, ids, _requests, state, head = _setup(tmp_path)
    import lunar_evolution.rsi_brs_reserved_ledger as module
    original = module._read_reserved_rows
    calls = []
    changed = deepcopy(state)
    changed["phase"] = "foreign-change"

    def race(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            ledger.write_controller_checkpoint("reserved", changed, expected_sha256=head)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_read_reserved_rows", race)
    with ledger.controller_lock("reserved"), pytest.raises(RSILearningError, match="rows_changed"):
        _read(ledger, ids, head)
    assert ledger.controller_checkpoint("reserved")[1] == changed


@pytest.mark.parametrize("table", ["rsi_python_admissions", "rsi_episode_reconciliations"])
def test_orphan_rows_remain_attempt_traces_without_episode_claim_or_current_fence(tmp_path, table):
    ledger, ids, _requests, _state, head = _setup(tmp_path)
    # These intentionally incomplete rows model interruption/corruption. Reading
    # them is never permission to classify the next child as fresh or settled.
    with ledger._connect() as connection:
        if table == "rsi_python_admissions":
            connection.execute(
                "INSERT INTO rsi_python_admissions VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("reserved", ids[1], "orphan-journal", "orphan-attempt", "{}", HEX, "fixture-time"),
            )
        else:
            connection.execute(
                "INSERT INTO rsi_episode_reconciliations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ids[1], 0, HEX, "unknown", "{}", None, HEX, "fixture-time"),
            )
    with ledger.controller_lock("reserved"):
        observed = _read(ledger, ids, head)
    trace = observed.ledger_traces()[ids[1]]
    assert trace["episode"] is trace["claim"] is trace["result"] is trace["obligation_sha256"] is None
    assert len(trace["admission_rows" if table == "rsi_python_admissions" else "reconciliation_rows"]) == 1


def test_corrupt_claim_digest_refuses_before_returning_any_observation(tmp_path):
    ledger, ids, requests, _state, head = _setup(tmp_path)
    plan = _plan(requests[1], EMPTY_MEMORY_SNAPSHOT)
    ledger.claim_native_episode(requests[1], plan_sha256=plan.plan_sha256)
    with ledger._connect() as connection:
        connection.execute("UPDATE rsi_native_episode_claims SET claim_sha256 = ? WHERE episode_id = ?",
                           (HEX, ids[1]))
    with ledger.controller_lock("reserved"), pytest.raises(RSILearningError, match="claim_corrupt"):
        _read(ledger, ids, head)


def test_original_observation_cannot_adopt_an_intervening_native_claim(tmp_path):
    ledger, ids, requests, _state, head = _setup(tmp_path)
    with ledger.controller_lock("reserved"):
        observation = _read(ledger, ids, head)
        assert_reserved_brs_ledger(ledger, observation)
        plan = _plan(requests[1], EMPTY_MEMORY_SNAPSHOT)
        claim = ledger.claim_native_episode(requests[1], plan_sha256=plan.plan_sha256)
        with pytest.raises(RSILearningError, match="observation_drift"):
            assert_reserved_brs_ledger(ledger, observation)
    assert observation.ledger_traces()[ids[1]]["claim"] is None
    assert ledger.inspect_native_episode_claim(requests[1], plan_sha256=plan.plan_sha256) == claim


def test_replaced_database_attribute_refuses_before_any_path_hook(tmp_path):
    ledger, ids, _requests, _state, head = _setup(tmp_path)

    class Trap:
        @property
        def parent(self):
            pytest.fail("caller path hook executed")

    original = ledger.database
    try:
        ledger.database = Trap()
        with pytest.raises(RSILearningError, match="ledger_path_invalid"):
            _read(ledger, ids, head)
    finally:
        ledger.database = original


@pytest.mark.parametrize("foreign_run,foreign_child", [(True, False), (False, True)])
def test_misassociated_admission_rows_cannot_disappear_from_original_domain(tmp_path, foreign_run, foreign_child):
    ledger, ids, _requests, _state, head = _setup(tmp_path)
    with ledger._connect() as connection:
        connection.execute(
            "INSERT INTO rsi_python_admissions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("foreign" if foreign_run else "reserved", "foreign-child" if foreign_child else ids[1],
             "orphan-journal", "orphan-attempt", "{}", HEX, "fixture-time"),
        )
    with ledger.controller_lock("reserved"), pytest.raises(RSILearningError, match="admission_domain_drift"):
        _read(ledger, ids, head)
