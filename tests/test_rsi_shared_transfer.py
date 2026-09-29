"""Explicit frozen panels consume the same durable budget as their learning run."""
from dataclasses import replace

import pytest
from test_bundle_population import draft_for_score
from test_rsi_transfer import block_run, profile, snapshot, task

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native import NativeIndependentVerifier, NativePopulationGateway
from lunar_evolution.rsi_stage_accounting import digest
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer import FrozenMemoryTransferBenchmark


def _learning_draft(request):
    return draft_for_score(5)


def _transfer_draft(request, readonly):
    return draft_for_score(7 if readonly.items else 5)


def setup_run(tmp_path, *, transfer_limit=1, verifier_limit=3, evaluator_limit=6, solver_limit=None):
    p = profile(tmp_path)
    root = tmp_path / "learning"
    controller = RSILearningController(
        NativePopulationGateway(p, _learning_draft, root, actor_fingerprint="b" * 64),
        verifier=NativeIndependentVerifier(p, root), ledger=RSILedger(tmp_path / "rsi.db"),
    )
    outcome = controller.run_drs(
        run_id="learning", contract_sha256=p.contract.digest(),
        evaluator_sha256=p.pipeline.evaluator.digest(), environment_sha256=p.pipeline.environment_sha256,
        solver_id="native_population", enable_transfer_accounting=True,
        budget={"max_transfer_invocations": transfer_limit, "max_evaluator_invocations": evaluator_limit,
                "max_verifier_invocations": verifier_limit, "max_solver_invocations": solver_limit},
    )
    assert outcome.status == "completed"
    benchmark = FrozenMemoryTransferBenchmark(_transfer_draft, tmp_path / "panels", actor_fingerprint="c" * 64)
    return controller, benchmark, task(p), snapshot(p.contract.digest())


def compare(controller, benchmark, panel_task, memory, *, comparison_id="panel"):
    return controller.compare_transfer(run_id="learning", benchmark=benchmark, comparison_id=comparison_id,
                                       tasks=(panel_task,), snapshot=memory)


def checkpoint(controller):
    return controller.ledger.controller_checkpoint("learning")[1]


def test_shared_panel_counts_and_retained_resume_do_not_repeat_work(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    before = checkpoint(controller)["budget_state"]["consumed"]
    assert before["evaluator_invocations"] == 2 and before["verifier_invocations"] == 1
    result = compare(controller, benchmark, panel_task, memory)
    assert result.status == "completed" and result.effect == "improved"
    state = checkpoint(controller)
    assert state["budget_state"]["consumed"] == {
        "solver_invocations": 3, "practice_episodes": 0, "unknown_retries": 0,
        "evaluator_invocations": 6, "verifier_invocations": 3, "transfer_invocations": 1,
    }
    panel = state["transfer_panels"]["panel"]
    assert panel["receipt_sha256"] == result.receipt_sha256
    assert all(row["evidence"] is not None for row in panel["stages"]["invocations"])
    assert not (result.receipt_path.parent / "stage-accounting.json").exists()
    block_run(monkeypatch)
    version = controller.ledger.controller_checkpoint("learning")[0]
    assert compare(controller, benchmark, panel_task, memory) == result
    assert controller.ledger.controller_checkpoint("learning")[0] == version
    assert controller.resume(run_id="learning").status == "completed"
    assert checkpoint(controller)["budget_state"] == state["budget_state"]


def test_shared_panel_identity_change_is_rejected_before_work(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    compare(controller, benchmark, panel_task, memory)
    block_run(monkeypatch)
    before = controller.ledger.controller_checkpoint("learning")
    with pytest.raises(RSILearningError, match="comparison_identity_changed"):
        compare(controller, benchmark, replace(panel_task, budget=(("candidate_attempts", 2),)), memory)
    assert controller.ledger.controller_checkpoint("learning") == before


@pytest.mark.parametrize("damage", ["drop_panel", "drop_stage", "rollback_counter", "verifier_identity"])
def test_shared_panel_history_rejects_erased_charges(tmp_path, monkeypatch, damage):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    compare(controller, benchmark, panel_task, memory)
    version, state = controller.ledger.controller_checkpoint("learning")
    if damage == "drop_panel":
        state["transfer_panels"] = {}
    elif damage == "drop_stage":
        state["transfer_panels"]["panel"]["stages"]["invocations"].pop()
    elif damage == "verifier_identity":
        verifier = next(row for row in state["transfer_panels"]["panel"]["stages"]["invocations"]
                        if row["stage"] == "verifier")
        verifier["identity"]["operation"]["verifier_fingerprint"] = "d" * 64
    else:
        state["budget_state"]["consumed"]["transfer_invocations"] = 0
        state["budget_state"]["remaining"]["transfer_invocations"] = 1
    with controller.ledger.controller_lock("learning"):
        controller.ledger.write_controller_checkpoint("learning", state, expected_sha256=version)
    block_run(monkeypatch)
    with pytest.raises(RSILearningError, match="checkpoint_invalid"):
        controller.resume(run_id="learning")


def test_shared_transfer_limit_stops_next_panel_before_actor(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    compare(controller, benchmark, panel_task, memory)
    before = checkpoint(controller)["budget_state"]
    block_run(monkeypatch)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        compare(controller, benchmark, panel_task, memory, comparison_id="second")
    assert checkpoint(controller)["budget_state"] == before
    assert compare(controller, benchmark, panel_task, memory, comparison_id="second").status == "unknown"


def test_shared_solver_budget_exhausts_before_second_arm_and_keeps_pending(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path, solver_limit=2)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        compare(controller, benchmark, panel_task, memory)
    state = checkpoint(controller)
    panel = state["transfer_panels"]["panel"]
    assert state["budget_state"]["consumed"]["solver_invocations"] == 2
    assert len(panel["solvers"]["invocations"]) == 1
    assert panel["solvers"]["invocations"][0]["result_sha256"] is not None
    block_run(monkeypatch)
    assert compare(controller, benchmark, panel_task, memory).status == "unknown"


@pytest.mark.parametrize("field", ["request_sha256", "result_sha256"])
def test_shared_solver_reservation_tamper_is_rejected_on_resume(tmp_path, field):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    compare(controller, benchmark, panel_task, memory)
    version, state = controller.ledger.controller_checkpoint("learning")
    row = state["transfer_panels"]["panel"]["solvers"]["invocations"][0]
    if field == "request_sha256":
        row["identity"][field] = "d" * 64
        row["intent_sha256"] = digest(row["identity"])
    else:
        row[field] = "e" * 64
    with controller.ledger.controller_lock("learning"):
        controller.ledger.write_controller_checkpoint("learning", state, expected_sha256=version)
    with pytest.raises(RSILearningError, match="(solver|checkpoint)_invalid"):
        controller.resume(run_id="learning")


def test_shared_panel_crash_keeps_reservation_and_forbids_relaunch(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    def interrupt(*args):
        state = checkpoint(controller)
        assert state["budget_state"]["consumed"]["transfer_invocations"] == 1
        assert state["transfer_panels"]["panel"]["stages"]["invocations"][0]["evidence"] is None
        raise RuntimeError("panel interrupted")
    monkeypatch.setattr(NativePopulationGateway, "run", interrupt)
    with pytest.raises(RuntimeError, match="panel interrupted"):
        compare(controller, benchmark, panel_task, memory)
    before = checkpoint(controller)["budget_state"]
    block_run(monkeypatch)
    result = compare(controller, benchmark, panel_task, memory)
    assert result.status == "unknown"
    assert checkpoint(controller)["budget_state"] == before


def test_shared_transfer_cannot_bypass_declared_opt_in(tmp_path):
    from lunar_evolution.rsi_gateway import DeterministicMockSolver
    controller = RSILearningController(DeterministicMockSolver(), ledger=RSILedger(tmp_path / "rsi.db"))
    pins = {"contract_sha256": "a" * 64, "evaluator_sha256": "a" * 64,
            "environment_sha256": "a" * 64, "solver_id": "mock"}
    with pytest.raises(RSILearningError, match="transfer_accounting_unavailable"):
        controller.run_drs(run_id="limited", **pins, budget={"max_transfer_invocations": 1})


@pytest.mark.parametrize("mode", ["drs", "brs"])
def test_transfer_accounting_opt_in_requires_durable_ledger(mode):
    from lunar_evolution.rsi_gateway import DeterministicMockSolver
    controller = RSILearningController(DeterministicMockSolver())
    pins = {"contract_sha256": "a" * 64, "evaluator_sha256": "a" * 64,
            "environment_sha256": "a" * 64, "solver_id": "mock"}
    with pytest.raises(RSILearningError, match="requires_ledger"):
        getattr(controller, "run_" + mode)(run_id="no-ledger", **pins, enable_transfer_accounting=True,
                                          **({"practices": ()} if mode == "brs" else {}))
