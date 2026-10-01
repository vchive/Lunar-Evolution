"""Explicit transfer recovery records evidence and never repeats uncertain callbacks."""

from __future__ import annotations

import copy
import hashlib

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_controller import FrozenMemoryTransferRunner
from lunar_evolution.rsi_gateway import DeterministicMockSolver, LocalExactVerifier
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


def digest(value):
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


class Gateway:
    def __init__(self, status="completed"):
        self.status, self.calls = status, 0

    def rsi_fingerprint_config(self):
        return {"status": self.status}

    def run(self, request):
        self.calls += 1
        return DeterministicMockSolver(terminal_status=self.status).run(request)


class Verifier(LocalExactVerifier):
    def __init__(self, crash=False):
        self.calls, self.crash, self.result, self.version = 0, crash, None, 1

    def rsi_fingerprint_config(self):
        return {"version": self.version}

    def verify(self, *args):
        self.calls += 1
        self.result = super().verify(*args)
        if self.crash:
            raise RuntimeError("callback_interrupted")
        return self.result


class Judge:
    def __init__(self, crash=False):
        self.calls, self.crash, self.result = 0, crash, None

    def rsi_fingerprint_config(self):
        return {"version": 1}

    def __call__(self, execution):
        self.calls += 1
        self.result = {"accepted": execution.passed, "diagnosis": "local acceptance"}
        if self.crash:
            raise RuntimeError("callback_interrupted")
        return self.result["accepted"], self.result["diagnosis"]


def setup(tmp_path, *, stage=None, status="completed", budget=None):
    ledger = RSILedger(tmp_path / "ledger.sqlite")
    gateway, verifier, judge = Gateway(status), Verifier(stage == "verifier"), Judge(stage == "judge")
    runner = FrozenMemoryTransferRunner(gateway, verifier, judge, ledger)
    kwargs = {"run_id": "learn", "target_id": "target", "contract_sha256": HEX, "evaluator_sha256": HEX,
                  "environment_sha256": HEX, "solver_id": "mock", "snapshot": EMPTY_MEMORY_SNAPSHOT, "budget": budget}
    return runner, ledger, gateway, verifier, judge, kwargs


def callback_args(runner, ledger, stage, verifier, judge):
    checkpoint, state = ledger.controller_checkpoint(runner._identity("learn", "target"))
    result = verifier.result.to_dict() if stage == "verifier" else judge.result
    return {"stage": stage, "expected_checkpoint_sha256": checkpoint, "result": result,
                "evidence": {"source": "local fixture observer", "binding_sha256": digest(state["intent"]),
                          "result_sha256": digest(result),
                          "receipt_sha256": result["receipt_sha256"] if stage == "verifier" else digest(result)}}


@pytest.mark.parametrize("stage", ["verifier", "judge"])
def test_reconciled_callback_resumes_once_and_exact_retry_is_read_only(tmp_path, stage):
    runner, ledger, gateway, verifier, judge, kwargs = setup(tmp_path, stage=stage,
                                                            budget={"max_unknown_retries": 1})
    with pytest.raises(RuntimeError, match="callback_interrupted"):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, stage, verifier, judge)
    runner.reconcile_callback("learn", "target", **args)
    assert runner.run(**kwargs)[0].status == "passed"
    history = ledger.controller_checkpoint_history(runner._identity("learn", "target"))
    assert history[-1][1]["budget_state"]["consumed"]["unknown_retries"] == 1
    runner.reconcile_callback("learn", "target", **args)
    assert runner.run(**kwargs)[0].status == "passed"
    assert ledger.controller_checkpoint_history(runner._identity("learn", "target")) == history
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)


@pytest.mark.parametrize("field", ["source", "binding_sha256", "result_sha256", "receipt_sha256"])
def test_callback_reconcile_rejects_bad_evidence_without_budget_or_callback(tmp_path, field):
    runner, ledger, gateway, verifier, judge, kwargs = setup(tmp_path, stage="verifier")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "verifier", verifier, judge)
    args["evidence"][field] = "" if field == "source" else "b" * 64
    before = ledger.controller_checkpoint(runner._identity("learn", "target"))
    with pytest.raises(RSILearningError):
        runner.reconcile_callback("learn", "target", **args)
    assert ledger.controller_checkpoint(runner._identity("learn", "target")) == before
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 0)


@pytest.mark.parametrize("field", ["episode_id", "contract_sha256", "evaluator_sha256", "environment_sha256",
                                  "candidate_receipt_sha256", "execution_receipt_sha256",
                                  "official_evaluation_receipt_sha256", "evidence_sha256", "extra"])
def test_callback_verifier_rejects_wrong_pins_even_with_rehashed_evidence(tmp_path, field):
    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="verifier")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "verifier", verifier, judge)
    args["result"][field] = "b" * 64
    args["evidence"]["result_sha256"] = digest(args["result"])
    with pytest.raises(RSILearningError):
        runner.reconcile_callback("learn", "target", **args)


@pytest.mark.parametrize("stage", ["verifier", "judge"])
def test_callback_result_can_be_recorded_after_deadline_but_new_callback_cannot_run(tmp_path, monkeypatch, stage):
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100)
    runner, ledger, gateway, verifier, judge, kwargs = setup(
        tmp_path, stage=stage, budget={"deadline_unix": 200, "max_unknown_retries": 1})
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, stage, verifier, judge)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 201)
    runner.reconcile_callback("learn", "target", **args)
    if stage == "verifier":
        with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
            runner.run(**kwargs)
    else:
        assert runner.run(**kwargs)[0].status == "passed"
    state = ledger.controller_checkpoint(runner._identity("learn", "target"))[1]
    assert state["budget_state"]["planned"]["deadline_unix"] == 200
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, stage == "judge")


def test_callback_reconcile_rejects_exhausted_unknown_budget_and_component_drift(tmp_path):
    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="verifier",
                                                            budget={"max_unknown_retries": 0})
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "verifier", verifier, judge)
    before = ledger.controller_checkpoint(runner._identity("learn", "target"))
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        runner.reconcile_callback("learn", "target", **args)
    verifier.version = 2
    with pytest.raises(RSILearningError, match="rsi_transfer_fingerprint_drift"):
        runner.reconcile_callback("learn", "target", **args)
    assert ledger.controller_checkpoint(runner._identity("learn", "target")) == before


def test_callback_reconcile_conflicting_retry_and_stale_checkpoint_fail(tmp_path):
    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="judge")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "judge", verifier, judge)
    with pytest.raises(RSILearningError, match="rsi_controller_checkpoint_conflict"):
        runner.reconcile_callback("learn", "target", **(args | {"expected_checkpoint_sha256": HEX}))
    runner.reconcile_callback("learn", "target", **args)
    bad = copy.deepcopy(args)
    bad["evidence"]["source"] = "another observer"
    with pytest.raises(RSILearningError, match="rsi_transfer_reconcile_conflict"):
        runner.reconcile_callback("learn", "target", **bad)


def settle(runner, ledger, execution, status):
    episode = ledger.get_episode(execution.episode.episode_id)
    ledger.reconcile_episode(episode.logical_id, worker_state=status, expected_record_sha256=episode.record_sha256,
                             evidence={"reconciliation": {"source": "local worker observation"}})
    published = ledger.get_transfer("learn", "target")
    head = ledger.get_episode(episode.logical_id)
    journal = ledger.episode_reconciliation(episode.logical_id)[-1]
    return {"expected_record_sha256": published.record_sha256,
                "evidence": {"source": "local transfer observer", "receipt_record_sha256": published.record_sha256,
                          "episode_record_sha256": head.record_sha256, "journal_sha256": journal["journal_sha256"]}}


@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out", "abandoned"])
def test_unknown_transfer_failure_revision_replays_without_callbacks_and_preserves_original(tmp_path, status):
    runner, ledger, gateway, verifier, judge, kwargs = setup(tmp_path, status="unknown",
                                                            budget={"max_unknown_retries": 1})
    receipt, execution = runner.run(**kwargs)
    original_wire = ledger.episode_result(execution.episode.episode_id)
    original_record = ledger.get_transfer("learn", "target")
    args = settle(runner, ledger, execution, status)
    record = runner.reconcile_receipt("learn", "target", **args)
    assert record.state == "failed"
    assert runner.reconcile_receipt("learn", "target", **args) == record
    replay_receipt, replay = runner.run(**kwargs)
    assert receipt.status == "unknown" and replay_receipt.status == "failed"
    assert replay.result.status == status and not replay.passed
    assert ledger.history(record.logical_id) == (original_record, record)
    assert ledger.episode_result(execution.episode.episode_id) == original_wire
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    assert ledger.controller_checkpoint(runner._identity("learn", "target"))[1]["budget_state"]["consumed"]["unknown_retries"] == 1


def test_transfer_unknown_cannot_be_settled_via_generic_transition_or_fake_evidence(tmp_path):
    runner, ledger, _gateway, _verifier, _judge, kwargs = setup(tmp_path, status="unknown")
    _receipt, execution = runner.run(**kwargs)
    record = ledger.get_transfer("learn", "target")
    with pytest.raises(RSILearningError, match="rsi_transfer_canonical_transition_required"):
        ledger.transition(record.logical_id, state="failed", expected_record_sha256=record.record_sha256)
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        runner.reconcile_receipt("learn", "target", expected_record_sha256=record.record_sha256, evidence={})
    args = settle(runner, ledger, execution, "cancelled")
    args["evidence"]["journal_sha256"] = HEX
    with pytest.raises(RSILearningError, match="rsi_transfer_reconcile_evidence_invalid"):
        runner.reconcile_receipt("learn", "target", **args)
    assert ledger.get_transfer("learn", "target") == record


def test_transfer_receipt_reconcile_cas_failure_rolls_back_checkpoint_and_receipt(tmp_path, monkeypatch):
    runner, ledger, _gateway, _verifier, _judge, kwargs = setup(tmp_path, status="unknown")
    _receipt, execution = runner.run(**kwargs)
    args = settle(runner, ledger, execution, "failed")
    internal = runner._identity("learn", "target")
    before = ledger.controller_checkpoint(internal)
    original = ledger._append_transfer_checkpoint_tx

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("transaction interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "_append_transfer_checkpoint_tx", crash)
        with pytest.raises(RuntimeError, match="transaction interrupted"):
            runner.reconcile_receipt("learn", "target", **args)
    assert ledger.controller_checkpoint(internal) == before
    assert ledger.get_transfer("learn", "target").state == "unknown"
    assert runner.reconcile_receipt("learn", "target", **args).state == "failed"


def test_receipt_failure_evidence_after_deadline_preserves_deadline_and_exhausted_budget_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100)
    runner, ledger, gateway, verifier, judge, kwargs = setup(
        tmp_path, status="unknown", budget={"deadline_unix": 200, "max_unknown_retries": 1})
    _receipt, execution = runner.run(**kwargs)
    args = settle(runner, ledger, execution, "cancelled")
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 201)
    record = runner.reconcile_receipt("learn", "target", **args)
    assert runner.run(**kwargs)[0].status == "failed"
    assert ledger.controller_checkpoint(runner._identity("learn", "target"))[1]["budget_state"]["planned"]["deadline_unix"] == 200
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    conflict = copy.deepcopy(args)
    conflict["evidence"]["source"] = "different observer"
    with pytest.raises(RSILearningError, match="rsi_transfer_reconcile_conflict"):
        runner.reconcile_receipt("learn", "target", **conflict)
    assert ledger.get_transfer("learn", "target") == record

    other, other_ledger, *_others, other_kwargs = setup(
        tmp_path / "exhausted", status="unknown", budget={"max_unknown_retries": 0})
    _, other_execution = other.run(**other_kwargs)
    other_args = settle(other, other_ledger, other_execution, "failed")
    before = other_ledger.controller_checkpoint(other._identity("learn", "target"))
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        other.reconcile_receipt("learn", "target", **other_args)
    assert other_ledger.controller_checkpoint(other._identity("learn", "target")) == before
    assert other_ledger.get_transfer("learn", "target").state == "unknown"


def test_callback_episode_cas_rejects_concurrent_worker_settlement(tmp_path, monkeypatch):
    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="verifier", status="unknown")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "verifier", verifier, judge)
    internal = runner._identity("learn", "target")
    before = ledger.controller_checkpoint(internal)
    original = ledger.write_transfer_reconciliation_checkpoint

    def settle_before_commit(*args, **kwargs):
        episode = ledger.get_episode(kwargs["episode_id"])
        ledger.reconcile_episode(episode.logical_id, worker_state="cancelled",
                                 expected_record_sha256=episode.record_sha256,
                                 evidence={"reconciliation": {"source": "worker exited"}})
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "write_transfer_reconciliation_checkpoint", settle_before_commit)
    with pytest.raises(RSILearningError, match="rsi_record_parent_conflict"):
        runner.reconcile_callback("learn", "target", **args)
    assert ledger.controller_checkpoint(internal) == before


@pytest.mark.parametrize("field", ["accepted", "diagnosis", "extra"])
def test_judge_reconciliation_requires_strict_result_schema(tmp_path, field):
    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="judge")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    args = callback_args(runner, ledger, "judge", verifier, judge)
    args["result"][field] = 1
    args["evidence"]["result_sha256"] = digest(args["result"])
    args["evidence"]["receipt_sha256"] = digest(args["result"])
    with pytest.raises(RSILearningError):
        runner.reconcile_callback("learn", "target", **args)


def test_generic_create_receipt_cannot_replace_unknown_with_failure(tmp_path):
    from dataclasses import replace

    runner, ledger, _gateway, _verifier, _judge, kwargs = setup(tmp_path, status="unknown")
    receipt, _execution = runner.run(**kwargs)
    with pytest.raises(RSILearningError, match="rsi_transfer_receipt_conflict"):
        ledger.create_transfer_receipt(replace(receipt, status="failed"))


def test_transfer_callback_reconcile_rejects_rolled_back_budget_checkpoint(tmp_path):
    from lunar_evolution.rsi_budget import RSIRunBudget

    runner, ledger, _gateway, verifier, judge, kwargs = setup(tmp_path, stage="judge")
    with pytest.raises(RuntimeError):
        runner.run(**kwargs)
    internal = runner._identity("learn", "target")
    checkpoint, state = ledger.controller_checkpoint(internal)
    state["budget_state"] = RSIRunBudget.create().to_dict()
    with ledger.controller_lock(internal):
        ledger.write_controller_checkpoint(internal, state, expected_sha256=checkpoint)
    args = callback_args(runner, ledger, "judge", verifier, judge)
    with pytest.raises(RSILearningError, match="rsi_resume_budget_drift"):
        runner.reconcile_callback("learn", "target", **args)
