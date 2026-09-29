"""Result-backed recovery of a retained shared transfer completion."""
import json
from unittest.mock import patch

import pytest
from test_rsi_shared_transfer import checkpoint, setup_run
from test_rsi_transfer import block_run

from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native import NativeIndependentVerifier, NativePopulationGateway
from lunar_evolution.rsi_recovery import DurableLearningRun
from lunar_evolution.rsi_stage_accounting import DurableSolverAccounting, DurableStageAccounting


def _pins(controller):
    state = checkpoint(controller)
    panel = state["transfer_panels"]["panel"]
    transfer = next(row for row in panel["stages"]["invocations"] if row["stage"] == "transfer")
    return state, panel, transfer


def _block_recovery_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("recovery launched work or reserved budget")

    for cls, method in ((NativePopulationGateway, "run"), (NativeIndependentVerifier, "verify"),
                        (DurableStageAccounting, "reserve"), (DurableSolverAccounting, "reserve"),
                        (RSIRunBudget, "reserve_stage"), (RSIRunBudget, "reserve_launch"),
                        (RSIRunBudget, "reserve_solver_invocation"), (RSIRunBudget, "reserve_unknown_reconcile")):
        monkeypatch.setattr(cls, method, forbidden)


def _interrupted_comparison(tmp_path, monkeypatch, window="transfer"):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    original_save = DurableLearningRun._save

    def fail_after_receipt(run):
        panel = run.state.get("transfer_panels", {}).get("panel")
        receipt = benchmark.workspace_root / "comparisons" / "panel" / "comparison.json"
        if panel and receipt.exists() and (window == "transfer" or panel["receipt_sha256"] is not None):
            raise RuntimeError("completion checkpoint interrupted")
        return original_save(run)

    with monkeypatch.context() as failed:
        failed.setattr(DurableLearningRun, "_save", fail_after_receipt)
        with pytest.raises(RuntimeError, match="completion checkpoint interrupted"):
            controller.compare_transfer(run_id="learning", benchmark=benchmark,
                                        comparison_id="panel", tasks=(panel_task,), snapshot=memory)
    _state, panel, transfer = _pins(controller)
    payload = json.loads((benchmark.workspace_root / "comparisons" / "panel" / "comparison.json").read_text())
    assert panel["receipt_sha256"] is None
    assert (transfer["evidence"] is None) == (window == "transfer")
    version = controller.ledger.controller_checkpoint("learning")[0]
    return controller, {
        "run_id": "learning", "benchmark": benchmark, "comparison_id": "panel",
        "tasks": (panel_task,), "snapshot": memory, "expected_record_sha256": version,
        "expected_intent_sha256": transfer["intent_sha256"], "expected_receipt_sha256": payload["receipt_sha256"],
    }


@pytest.mark.parametrize("window", ["transfer", "panel"])
def test_reconcile_retained_comparison_after_completion_checkpoint_failure(tmp_path, monkeypatch, window):
    controller, args = _interrupted_comparison(tmp_path, monkeypatch, window)
    before_budget = checkpoint(controller)["budget_state"]
    _block_recovery_work(monkeypatch)
    result = controller.reconcile_transfer(**args)
    assert result.status == "completed"
    version, recovered = controller.ledger.controller_checkpoint("learning")
    assert recovered["transfer_panels"]["panel"]["receipt_sha256"] == args["expected_receipt_sha256"]
    assert recovered["budget_state"] == before_budget
    assert controller.reconcile_transfer(**args) == result
    assert controller.ledger.controller_checkpoint("learning")[0] == version
    assert controller.resume(run_id="learning").status == "completed"
    resumed = checkpoint(controller)
    assert resumed["budget_state"] == before_budget
    assert resumed["transfer_panels"] == recovered["transfer_panels"]


def test_reconcile_is_idempotent_and_does_not_launch(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    result = controller.compare_transfer(run_id="learning", benchmark=benchmark,
                                         comparison_id="panel", tasks=(panel_task,), snapshot=memory)
    version = controller.ledger.controller_checkpoint("learning")[0]
    _state, _panel, transfer = _pins(controller)
    _block_recovery_work(monkeypatch)
    again = controller.reconcile_transfer(
        run_id="learning", benchmark=benchmark, comparison_id="panel", tasks=(panel_task,), snapshot=memory,
        expected_record_sha256=version, expected_intent_sha256=transfer["intent_sha256"],
        expected_receipt_sha256=result.receipt_sha256,
    )
    assert again == result
    assert controller.ledger.controller_checkpoint("learning")[0] == version


@pytest.mark.parametrize("pin", ["record", "intent", "receipt"])
def test_reconcile_rejects_changed_pins(tmp_path, pin):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    result = controller.compare_transfer(run_id="learning", benchmark=benchmark,
                                         comparison_id="panel", tasks=(panel_task,), snapshot=memory)
    version = controller.ledger.controller_checkpoint("learning")[0]
    _state, _panel, transfer = _pins(controller)
    args = {"expected_record_sha256": version, "expected_intent_sha256": transfer["intent_sha256"],
            "expected_receipt_sha256": result.receipt_sha256}
    args[f"expected_{pin}_sha256"] = "0" * 64
    with pytest.raises(RSILearningError, match="reconcile_(record|intent|receipt)"):
        controller.reconcile_transfer(run_id="learning", benchmark=benchmark,
                                      comparison_id="panel", tasks=(panel_task,), snapshot=memory, **args)


def test_reconcile_missing_comparison_remains_unknown_without_checkpoint_mutation(tmp_path):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    # Create only the controller panel intent/reservations through a failed first arm.
    def interrupted(*_args):
        raise RuntimeError("arm interrupted")
    with patch.object(NativePopulationGateway, "run", interrupted), pytest.raises(
        RuntimeError, match="arm interrupted",
    ):
        controller.compare_transfer(run_id="learning", benchmark=benchmark,
                                    comparison_id="panel", tasks=(panel_task,), snapshot=memory)
    version, _before = controller.ledger.controller_checkpoint("learning")
    _state, _panel, transfer = _pins(controller)
    result = controller.reconcile_transfer(
        run_id="learning", benchmark=benchmark, comparison_id="panel", tasks=(panel_task,), snapshot=memory,
        expected_record_sha256=version, expected_intent_sha256=transfer["intent_sha256"],
        expected_receipt_sha256="3" * 64,
    )
    assert result.status == "unknown"
    assert controller.ledger.controller_checkpoint("learning")[0] == version


def test_reconcile_rejects_tampered_retained_comparison(tmp_path, monkeypatch):
    controller, benchmark, panel_task, memory = setup_run(tmp_path)
    result = controller.compare_transfer(run_id="learning", benchmark=benchmark,
                                         comparison_id="panel", tasks=(panel_task,), snapshot=memory)
    version = controller.ledger.controller_checkpoint("learning")[0]
    _state, _panel, transfer = _pins(controller)
    path = benchmark.workspace_root / "comparisons" / "panel" / "comparison.json"
    payload = json.loads(path.read_text())
    payload["summary"]["effect"] = "unresolved"
    path.write_text(json.dumps(payload))
    before = controller.ledger.controller_checkpoint("learning")
    block_run(monkeypatch)
    with pytest.raises(RSILearningError, match="rsi_transfer_record_invalid"):
        controller.reconcile_transfer(
            run_id="learning", benchmark=benchmark, comparison_id="panel", tasks=(panel_task,), snapshot=memory,
            expected_record_sha256=version, expected_intent_sha256=transfer["intent_sha256"],
            expected_receipt_sha256=result.receipt_sha256,
        )
    assert controller.ledger.controller_checkpoint("learning") == before


def test_reconcile_rejects_changed_independent_evidence(tmp_path, monkeypatch):
    controller, args = _interrupted_comparison(tmp_path, monkeypatch)
    root = args["benchmark"].workspace_root / "comparisons" / "panel"
    path = next(root.glob("tasks/*/verifications/*/verifier-receipt.json"))
    path.write_text("{}")
    before = controller.ledger.controller_checkpoint("learning")
    _block_recovery_work(monkeypatch)
    with pytest.raises(RSILearningError, match="verification_receipt_changed"):
        controller.reconcile_transfer(**args)
    assert controller.ledger.controller_checkpoint("learning") == before


@pytest.mark.parametrize("damage", ["remove", "replace"])
def test_reconciliation_audit_cannot_be_rewritten(tmp_path, monkeypatch, damage):
    controller, args = _interrupted_comparison(tmp_path, monkeypatch)
    controller.reconcile_transfer(**args)
    version, state = controller.ledger.controller_checkpoint("learning")
    if damage == "remove":
        state.pop("transfer_reconciliations")
    else:
        state["transfer_reconciliations"]["panel"]["checkpoint_sha256"] = "0" * 64
    with controller.ledger.controller_lock("learning"):
        controller.ledger.write_controller_checkpoint("learning", state, expected_sha256=version)
    _block_recovery_work(monkeypatch)
    with pytest.raises(RSILearningError, match="checkpoint_invalid"):
        controller.resume(run_id="learning")


def test_failed_reconcile_checkpoint_can_retry_with_same_pins(tmp_path, monkeypatch):
    controller, args = _interrupted_comparison(tmp_path, monkeypatch)
    before = controller.ledger.controller_checkpoint("learning")
    _block_recovery_work(monkeypatch)

    def interrupted(_run):
        raise RuntimeError("reconcile checkpoint interrupted")

    with monkeypatch.context() as failed:
        failed.setattr(DurableLearningRun, "_save", interrupted)
        with pytest.raises(RuntimeError, match="reconcile checkpoint interrupted"):
            controller.reconcile_transfer(**args)
    assert controller.ledger.controller_checkpoint("learning") == before
    assert controller.reconcile_transfer(**args).status == "completed"


@pytest.mark.parametrize("stage", ["solver", "verifier", "evaluator"])
def test_reconcile_cannot_complete_pending_inner_reservations(tmp_path, monkeypatch, stage):
    if stage == "solver":
        original_complete = DurableSolverAccounting.complete

        def skip_transfer_solver(accounting, row, result_sha256):
            if row["identity"].get("comparison_id") != "panel":
                return original_complete(accounting, row, result_sha256)

        monkeypatch.setattr(DurableSolverAccounting, "complete", skip_transfer_solver)
    else:
        original_complete = DurableStageAccounting.complete

        def skip_transfer_stage(accounting, row, receipt_sha256):
            owner = row["identity"].get("owner", {})
            if row["stage"] != stage or owner.get("comparison_id") != "panel":
                return original_complete(accounting, row, receipt_sha256)

        monkeypatch.setattr(DurableStageAccounting, "complete", skip_transfer_stage)
    controller, args = _interrupted_comparison(tmp_path, monkeypatch)
    before = controller.ledger.controller_checkpoint("learning")
    _block_recovery_work(monkeypatch)
    with pytest.raises(RSILearningError, match="inner_work_pending"):
        controller.reconcile_transfer(**args)
    assert controller.ledger.controller_checkpoint("learning") == before
