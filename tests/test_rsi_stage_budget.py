"""Durable stage reservations must precede work and never authorize uncertain replay."""
import sqlite3
from dataclasses import replace

import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import (
    DeterministicMockSolver,
    LocalExactVerifier,
    SolverRequest,
    SolverResult,
)
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_recovery import DurableLearningRun, digest
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
PINS = {"contract_sha256": HEX, "evaluator_sha256": HEX, "environment_sha256": HEX, "solver_id": "mock"}


class Gateway:
    def __init__(self, statuses=()):
        self.statuses = list(statuses)
        self.requests = []

    def fingerprint(self):
        return "b" * 64

    def run(self, request):
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else "completed"
        return DeterministicMockSolver(terminal_status=status).run(request)


class Verifier(LocalExactVerifier):
    def __init__(self):
        self.calls = 0

    def verify(self, *args):
        self.calls += 1
        return super().verify(*args)


def controller(tmp_path, gateway, verifier):
    return RSILearningController(gateway, verifier=verifier, ledger=RSILedger(tmp_path / "rsi.db"))


def test_zero_verifier_budget_stops_before_verifier_and_remains_terminal(tmp_path):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    result = first.run_drs(run_id="zero", **PINS, budget={"max_verifier_invocations": 0})
    assert result.status == "budget_exhausted"
    assert len(gateway.requests) == 1 and verifier.calls == 0
    checkpoint = first.ledger.controller_checkpoint("zero")[1]
    assert checkpoint["budget_state"]["consumed"]["verifier_invocations"] == 0
    assert checkpoint["episodes"]["zero-target-0"]["verifier_invocations"] == []
    resumed_gateway = Gateway()
    assert controller(tmp_path, resumed_gateway, verifier).resume(run_id="zero").status == "budget_exhausted"
    assert resumed_gateway.requests == [] and verifier.calls == 0


def test_saved_verifier_decision_reuses_its_reservation_on_resume(tmp_path):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    done = first.run_drs(run_id="saved", **PINS, budget={"max_verifier_invocations": 1})
    assert done.status == "completed" and verifier.calls == 1
    assert controller(tmp_path, Gateway(), verifier).resume(run_id="saved") == done
    checkpoint = first.ledger.controller_checkpoint("saved")[1]
    assert checkpoint["budget_state"]["consumed"]["verifier_invocations"] == 1
    assert checkpoint["budget_state"]["remaining"]["verifier_invocations"] == 0
    assert verifier.calls == 1


def test_verifier_intent_is_durable_before_work_and_crash_is_quarantined(tmp_path):
    class InterruptedVerifier(Verifier):
        def verify(self, episode, request, result):
            self.calls += 1
            checkpoint = first.ledger.controller_checkpoint("intent")[1]
            intent = checkpoint["episodes"][episode.episode_id]["verifier_invocations"][0]
            assert checkpoint["budget_state"]["consumed"]["verifier_invocations"] == 1
            assert intent["request_sha256"] == request.digest()
            assert intent["episode_record_sha256"] == episode.record_sha256
            assert intent["decision"] is None
            raise RuntimeError("verifier interrupted")

    gateway, verifier = Gateway(), InterruptedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="verifier interrupted"):
        first.run_drs(run_id="intent", **PINS, budget={"max_verifier_invocations": 2})
    resumed_gateway = Gateway()
    assert controller(tmp_path, resumed_gateway, verifier).resume(run_id="intent").status == "unknown"
    assert resumed_gateway.requests == [] and verifier.calls == 1
    assert first.ledger.get("intent-target-0").state == "completed"


def test_decision_checkpoint_failure_never_repeats_finished_verifier(tmp_path, monkeypatch):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    original = DurableLearningRun._save

    def fail_before_decision_save(run):
        if any(entry.get("verifier_decision") for entry in run.state["episodes"].values()):
            raise RuntimeError("decision checkpoint interrupted")
        return original(run)

    with monkeypatch.context() as patch:
        patch.setattr(DurableLearningRun, "_save", fail_before_decision_save)
        with pytest.raises(RuntimeError, match="decision checkpoint interrupted"):
            first.run_drs(run_id="decision", **PINS, budget={"max_verifier_invocations": 2})
    assert controller(tmp_path, Gateway(), verifier).resume(run_id="decision").status == "unknown"
    assert verifier.calls == 1


class RetainedVerifier(Verifier):
    def __init__(self):
        super().__init__()
        self.saved_decision = None

    def verify(self, *args):
        self.saved_decision = super().verify(*args)
        raise RuntimeError("retained verifier interrupted")

def test_explicit_verifier_reconciliation_reopens_evidence_without_execution(tmp_path):
    gateway, verifier = Gateway(), RetainedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="retained verifier interrupted"):
        first.run_drs(run_id="retained", **PINS,
                      budget={"max_verifier_invocations": 1, "max_unknown_retries": 1})
    assert first.resume(run_id="retained").status == "unknown"
    checkpoint = first.ledger.controller_checkpoint("retained")[1]
    entry = checkpoint["episodes"]["retained-target-0"]
    solver_result = dict(entry["result"])
    intent_pin = digest(entry["verifier_invocations"][0])
    head = first.ledger.get("retained-target-0")
    done = first.reconcile_verifier(run_id="retained", episode_id="retained-target-0",
                                    decision=verifier.saved_decision,
                                    expected_record_sha256=head.record_sha256,
                                    expected_intent_sha256=intent_pin)
    assert done.status == "completed" and verifier.calls == 1
    checkpoint = first.ledger.controller_checkpoint("retained")[1]
    assert checkpoint["episodes"]["retained-target-0"]["result"] == solver_result
    assert checkpoint["budget_state"]["consumed"]["verifier_invocations"] == 1
    assert checkpoint["budget_state"]["consumed"]["unknown_retries"] == 0
    head = first.ledger.get("retained-target-0")
    assert first.reconcile_verifier(run_id="retained", episode_id="retained-target-0",
                                    decision=verifier.saved_decision,
                                    expected_record_sha256=head.record_sha256,
                                    expected_intent_sha256=intent_pin) == done
    with pytest.raises(RSILearningError, match="rsi_verifier_reconcile_intent_conflict"):
        first.reconcile_verifier(run_id="retained", episode_id="retained-target-0",
                                 decision=verifier.saved_decision,
                                 expected_record_sha256=head.record_sha256,
                                 expected_intent_sha256="c" * 64)
    assert verifier.calls == 1


def test_explicit_verifier_reconciliation_rejects_intent_drift_and_untrusted_decision(tmp_path):
    gateway, verifier = Gateway(), RetainedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="retained verifier interrupted"):
        first.run_drs(run_id="drift", **PINS)
    checkpoint = first.ledger.controller_checkpoint("drift")[1]
    entry = checkpoint["episodes"]["drift-target-0"]
    intent_pin = digest(entry["verifier_invocations"][0])
    head = first.ledger.get("drift-target-0")
    run = DurableLearningRun(first, "drift")
    with pytest.raises(RSILearningError, match="rsi_verifier_reconcile_intent_conflict"):
        run.reconcile_verifier("drift-target-0", verifier.saved_decision,
                               expected_record_sha256=head.record_sha256,
                               expected_intent_sha256="c" * 64)
    with pytest.raises(RSILearningError, match="rsi_verifier_retained_decision_mismatch"):
        run.reconcile_verifier("drift-target-0", replace(verifier.saved_decision, receipt_sha256="c" * 64),
                               expected_record_sha256=head.record_sha256,
                               expected_intent_sha256=intent_pin)
    checkpoint = first.ledger.controller_checkpoint("drift")[1]
    assert digest(checkpoint["episodes"]["drift-target-0"]["verifier_invocations"][0]) == intent_pin
    assert checkpoint["budget_state"]["consumed"]["unknown_retries"] == 0
    assert verifier.calls == 1


def test_durable_pending_intent_can_reconcile_without_any_verifier_execution(tmp_path, monkeypatch):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    original = DurableLearningRun._save

    def fail_after_intent_save(run):
        original(run)
        if any(entry["verifier_invocations"] for entry in run.state["episodes"].values()):
            raise RuntimeError("stopped after verifier intent")

    with monkeypatch.context() as patch:
        patch.setattr(DurableLearningRun, "_save", fail_after_intent_save)
        with pytest.raises(RuntimeError, match="stopped after verifier intent"):
            first.run_drs(run_id="pending", **PINS, budget={"max_verifier_invocations": 1})
    assert verifier.calls == 0
    assert first.resume(run_id="pending").status == "unknown"
    checkpoint = first.ledger.controller_checkpoint("pending")[1]
    entry = checkpoint["episodes"]["pending-target-0"]
    episode = PracticeEpisode.from_dict(entry["episode"])
    request = SolverRequest.from_dict(entry["request"])
    result = SolverResult.from_dict(entry["result"])
    retained = LocalExactVerifier()._reconstruct_decision(episode, request, result)
    head = first.ledger.get("pending-target-0")
    done = first.reconcile_verifier(run_id="pending", episode_id="pending-target-0", decision=retained,
                                    expected_record_sha256=head.record_sha256,
                                    expected_intent_sha256=digest(entry["verifier_invocations"][0]))
    assert done.status == "completed" and verifier.calls == 0
    assert len(gateway.requests) == 1
    assert first.ledger.controller_checkpoint("pending")[1]["budget_state"] == checkpoint["budget_state"]


def test_unknown_diagnostic_verifier_receipt_reconciles_without_terminal_solver_evidence(tmp_path):
    gateway, verifier = Gateway(("unknown",)), RetainedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="retained verifier interrupted"):
        first.run_drs(run_id="diagnostic", **PINS, budget={"max_verifier_invocations": 1})
    assert first.resume(run_id="diagnostic").status == "unknown"
    checkpoint = first.ledger.controller_checkpoint("diagnostic")[1]
    entry = checkpoint["episodes"]["diagnostic-target-0"]
    intent_pin = digest(entry["verifier_invocations"][0])
    head = first.ledger.get("diagnostic-target-0")
    reconciled = first.reconcile_verifier(run_id="diagnostic", episode_id="diagnostic-target-0",
                                         decision=verifier.saved_decision,
                                         expected_record_sha256=head.record_sha256,
                                         expected_intent_sha256=intent_pin)
    assert reconciled.status == "unknown"
    assert reconciled.target_attempts[0].verifier == verifier.saved_decision
    assert reconciled.target_attempts[0].result.status == "unknown"
    assert first.resume(run_id="diagnostic") == reconciled
    assert verifier.calls == 1 and len(gateway.requests) == 1
    assert first.ledger.controller_checkpoint("diagnostic")[1]["budget_state"] == checkpoint["budget_state"]


def test_retained_verifier_reconciliation_cannot_revive_budget_exhausted_run(tmp_path):
    gateway, verifier = Gateway(("unknown",)), RetainedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="retained verifier interrupted"):
        first.run_drs(run_id="terminal", **PINS,
                      budget={"max_verifier_invocations": 1, "max_unknown_retries": 0})
    request = gateway.requests[0]
    head = first.ledger.get(request.episode_id)
    exhausted = first.reconcile_episode(run_id="terminal", episode_id=request.episode_id,
                                        result=DeterministicMockSolver().run(request),
                                        expected_record_sha256=head.record_sha256)
    assert exhausted.status == "budget_exhausted"
    checkpoint = first.ledger.controller_checkpoint("terminal")[1]
    entry = checkpoint["episodes"][request.episode_id]
    head = first.ledger.get(request.episode_id)
    with pytest.raises(RSILearningError, match="rsi_verifier_reconcile_state_invalid"):
        first.reconcile_verifier(run_id="terminal", episode_id=request.episode_id,
                                 decision=verifier.saved_decision,
                                 expected_record_sha256=head.record_sha256,
                                 expected_intent_sha256=digest(entry["verifier_invocations"][0]))
    assert first.resume(run_id="terminal").status == "budget_exhausted"
    assert verifier.calls == 1 and len(gateway.requests) == 1
    assert first.ledger.controller_checkpoint("terminal")[1]["budget_state"] == checkpoint["budget_state"]


def test_checkpoint_history_rejects_erased_verifier_intent_and_counter(tmp_path, monkeypatch):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    original = DurableLearningRun._save
    stopped = False

    def stop_after_intent(run):
        nonlocal stopped
        original(run)
        if not stopped and any(entry["verifier_invocations"] for entry in run.state["episodes"].values()):
            stopped = True
            raise RuntimeError("intent checkpoint stop")

    with pytest.raises(RuntimeError, match="intent checkpoint stop"), monkeypatch.context() as patch:
        patch.setattr(DurableLearningRun, "_save", stop_after_intent)
        first.run_drs(run_id="history", **PINS, budget={"max_verifier_invocations": 2})
    version, checkpoint = first.ledger.controller_checkpoint("history")
    entry = checkpoint["episodes"]["history-target-0"]
    entry["verifier_invocations"] = []
    checkpoint["budget_state"]["consumed"]["verifier_invocations"] = 0
    checkpoint["budget_state"]["remaining"]["verifier_invocations"] = 2
    with first.ledger.controller_lock("history"):
        first.ledger.write_controller_checkpoint("history", checkpoint, expected_sha256=version)
    assert len(first.ledger.controller_checkpoint_history("history")) >= 2
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        controller(tmp_path, Gateway(), Verifier()).resume(run_id="history")


def test_checkpoint_history_rejects_verifier_counter_regression(tmp_path):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    first.run_drs(run_id="counter-history", **PINS, budget={"max_verifier_invocations": 2})
    version, checkpoint = first.ledger.controller_checkpoint("counter-history")
    checkpoint["budget_state"]["consumed"]["verifier_invocations"] = 0
    checkpoint["budget_state"]["remaining"]["verifier_invocations"] = 2
    with first.ledger.controller_lock("counter-history"):
        first.ledger.write_controller_checkpoint("counter-history", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        controller(tmp_path, Gateway(), Verifier()).resume(run_id="counter-history")


@pytest.mark.parametrize("field", ["result_sha256", "decision_kind", "verifier_fingerprint", "decision", "reconciliation"])
def test_checkpoint_history_rejects_rewriting_retained_verifier_intent(tmp_path, field):
    gateway, verifier = Gateway(), RetainedVerifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RuntimeError, match="retained verifier interrupted"):
        first.run_drs(run_id="rewrite", **PINS)
    entry = first.ledger.controller_checkpoint("rewrite")[1]["episodes"]["rewrite-target-0"]
    head = first.ledger.get("rewrite-target-0")
    first.reconcile_verifier(run_id="rewrite", episode_id="rewrite-target-0", decision=verifier.saved_decision,
                             expected_record_sha256=head.record_sha256,
                             expected_intent_sha256=digest(entry["verifier_invocations"][0]))
    version, checkpoint = first.ledger.controller_checkpoint("rewrite")
    intent = checkpoint["episodes"]["rewrite-target-0"]["verifier_invocations"][0]
    if field in {"decision", "reconciliation"}:
        intent[field] = None
    elif field == "decision_kind":
        intent[field] = "diagnostic"
    else:
        intent[field] = "c" * 64
    with first.ledger.controller_lock("rewrite"):
        first.ledger.write_controller_checkpoint("rewrite", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_budget_checkpoint_invalid"):
        first.resume(run_id="rewrite")


def test_checkpoint_history_returns_detached_verified_append_order(tmp_path):
    ledger = RSILedger(tmp_path / "history.db")
    assert ledger.controller_checkpoint_history("absent") == []
    assert ledger.controller_checkpoint("absent") is None
    with ledger.controller_lock("history"):
        first = ledger.write_controller_checkpoint("history", {"legacy": 1}, expected_sha256=None)
        second = ledger.write_controller_checkpoint("history", {"legacy": 2}, expected_sha256=first)
    history = ledger.controller_checkpoint_history("history")
    assert history == [(first, {"legacy": 1}), (second, {"legacy": 2})]
    history[0][1]["legacy"] = 99
    assert ledger.controller_checkpoint_history("history")[0] == (first, {"legacy": 1})
    assert ledger.controller_checkpoint("history") == (second, {"legacy": 2})
    with sqlite3.connect(ledger.database) as connection:
        connection.execute("UPDATE rsi_controller_journal SET payload = ? WHERE run_id = ? AND revision = ?",
                           ('{"legacy":99}', "history", 0))
    with pytest.raises(RSILearningError, match="rsi_controller_checkpoint_corrupt"):
        ledger.controller_checkpoint_history("history")


def test_reconciliation_charges_new_result_once_and_retains_prior_intent(tmp_path):
    gateway, verifier = Gateway(("unknown",)), Verifier()
    first = controller(tmp_path, gateway, verifier)
    assert first.run_drs(run_id="reconciled", **PINS, budget={"max_verifier_invocations": 2}).status == "unknown"
    request = gateway.requests[0]
    evidence = DeterministicMockSolver().run(request)
    head = first.ledger.get(request.episode_id)
    done = first.reconcile_episode(run_id="reconciled", episode_id=request.episode_id,
                                   result=evidence, expected_record_sha256=head.record_sha256)
    assert done.status == "completed" and verifier.calls == 2
    checkpoint = first.ledger.controller_checkpoint("reconciled")[1]
    entry = checkpoint["episodes"][request.episode_id]
    assert [intent["decision_kind"] for intent in entry["verifier_invocations"]] == ["diagnostic", "completion"]
    assert checkpoint["budget_state"]["consumed"]["verifier_invocations"] == 2
    head = first.ledger.get(request.episode_id)
    assert first.reconcile_episode(run_id="reconciled", episode_id=request.episode_id,
                                   result=evidence, expected_record_sha256=head.record_sha256) == done
    assert verifier.calls == 2


def test_reconciliation_stops_when_new_verifier_reservation_is_unavailable(tmp_path):
    gateway, verifier = Gateway(("unknown",)), Verifier()
    first = controller(tmp_path, gateway, verifier)
    assert first.run_drs(run_id="bounded", **PINS, budget={"max_verifier_invocations": 1}).status == "unknown"
    request = gateway.requests[0]
    head = first.ledger.get(request.episode_id)
    done = first.reconcile_episode(run_id="bounded", episode_id=request.episode_id,
                                   result=DeterministicMockSolver().run(request),
                                   expected_record_sha256=head.record_sha256)
    assert done.status == "budget_exhausted" and verifier.calls == 1
    assert controller(tmp_path, Gateway(), verifier).resume(run_id="bounded").status == "budget_exhausted"
    assert verifier.calls == 1


@pytest.mark.parametrize("change", ["undercount", "overcount", "receipt", "result", "duplicate", "remove"])
def test_resume_rejects_counts_or_reservations_that_do_not_match_evidence(tmp_path, change):
    first = controller(tmp_path, Gateway(), Verifier())
    first.run_drs(run_id="tampered", **PINS, budget={"max_verifier_invocations": 3})
    version, checkpoint = first.ledger.controller_checkpoint("tampered")
    entry = checkpoint["episodes"]["tampered-target-0"]
    if change in {"undercount", "overcount"}:
        consumed = 0 if change == "undercount" else 2
        checkpoint["budget_state"]["consumed"]["verifier_invocations"] = consumed
        checkpoint["budget_state"]["remaining"]["verifier_invocations"] = 3 - consumed
    elif change == "receipt":
        entry["verifier_invocations"][0]["episode_record_sha256"] = "c" * 64
    elif change == "result":
        entry["verifier_invocations"][0]["result_sha256"] = "c" * 64
    elif change == "duplicate":
        entry["verifier_invocations"].append(dict(entry["verifier_invocations"][0]))
        checkpoint["budget_state"]["consumed"]["verifier_invocations"] = 2
        checkpoint["budget_state"]["remaining"]["verifier_invocations"] = 1
    else:
        entry["verifier_invocations"] = []
        entry.pop("verifier_decision")
        entry["episode"]["verifier"] = None
        checkpoint["budget_state"]["consumed"]["verifier_invocations"] = 0
        checkpoint["budget_state"]["remaining"]["verifier_invocations"] = 3
    with first.ledger.controller_lock("tampered"):
        first.ledger.write_controller_checkpoint("tampered", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError):
        controller(tmp_path, Gateway(), Verifier()).resume(run_id="tampered")


@pytest.mark.parametrize("stage", ["evaluator", "transfer"])
@pytest.mark.parametrize("limit", [0, 2])
def test_unconnected_finite_stage_budget_fails_before_any_solver_work(tmp_path, stage, limit):
    gateway, verifier = Gateway(), Verifier()
    first = controller(tmp_path, gateway, verifier)
    with pytest.raises(RSILearningError, match=f"rsi_budget_{stage}_accounting_unavailable"):
        first.run_drs(run_id="unconnected", **PINS, budget={f"max_{stage}_invocations": limit})
    assert gateway.requests == [] and verifier.calls == 0
    assert first.ledger.controller_checkpoint("unconnected") is None
