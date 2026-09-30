"""Frozen transfer recovery must reuse one namespaced side effect and durable verdict."""

from __future__ import annotations

import threading

import pytest

from lunar_evolution.rsi_controller import FrozenMemoryTransferRunner
from lunar_evolution.rsi_gateway import DeterministicMockSolver, LocalExactVerifier
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64


class Gateway:
    def __init__(self, status="completed"):
        self.calls = 0
        self.status = status

    def rsi_fingerprint_config(self):
        return {"status": self.status}

    def run(self, request):
        self.calls += 1
        return DeterministicMockSolver(terminal_status=self.status).run(request)


class Verifier(LocalExactVerifier):
    def __init__(self, version=1):
        self.calls = 0
        self.version = version

    def rsi_fingerprint_config(self):
        return {"version": self.version}

    def verify(self, episode, request, result):
        self.calls += 1
        return super().verify(episode, request, result)


class Judge:
    def __init__(self):
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"version": 1}

    def __call__(self, execution):
        self.calls += 1
        return execution.passed, "local transfer acceptance"


def _kwargs(**extra):
    return {
        "run_id": "learning-run", "target_id": "transfer-target",
        "contract_sha256": HEX, "evaluator_sha256": HEX, "environment_sha256": HEX,
        "solver_id": "mock", "snapshot": EMPTY_MEMORY_SNAPSHOT,
    } | extra


def _runner(tmp_path, status="completed"):
    ledger = RSILedger(tmp_path / "transfer.sqlite")
    gateway, verifier, judge = Gateway(status), Verifier(), Judge()
    runner = FrozenMemoryTransferRunner(gateway, verifier, judge, ledger)
    return runner, ledger, gateway, verifier, judge


def _fresh(ledger, gateway, verifier, judge):
    return FrozenMemoryTransferRunner(gateway, verifier, judge, RSILedger(ledger.database))


def test_terminal_transfer_replays_without_solver_verifier_judge_or_ledger_writes(tmp_path):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    first = runner.run(**_kwargs())
    internal = runner._identity("learning-run", "transfer-target")
    history = ledger.controller_checkpoint_history(internal)
    episode_history = ledger.history(first[1].episode.episode_id)
    second = _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert second == first
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    assert ledger.controller_checkpoint_history(internal) == history
    assert ledger.history(first[1].episode.episode_id) == episode_history
    assert ledger.episode_ids_for_run("learning-run") == ()
    assert ledger.episode_ids_for_run(internal) == (first[1].episode.episode_id,)


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"])
def test_transfer_recovers_after_result_publication_without_relaunch(tmp_path, monkeypatch, status):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path, status)
    save = ledger.save_episode_result

    def crash(request, result):
        save(request, result)
        raise RuntimeError("after_result")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash)
        with pytest.raises(RuntimeError, match="after_result"):
            runner.run(**_kwargs())
    result = _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert result[0].status == ("passed" if status == "completed" else "unknown" if status == "unknown" else "failed")
    assert result[1].result.status == status
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    assert _fresh(ledger, gateway, verifier, judge).run(**_kwargs()) == result
    assert gateway.calls == verifier.calls == judge.calls == 1


def test_transfer_recovers_after_verdict_before_episode_append_without_verifier_replay(tmp_path, monkeypatch):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    append = ledger.append_episode_record

    def crash(episode, **kwargs):
        if episode.verifier is not None:
            raise RuntimeError("before_verifier_append")
        return append(episode, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "append_episode_record", crash)
        with pytest.raises(RuntimeError, match="before_verifier_append"):
            runner.run(**_kwargs())
    receipt, _execution = _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert receipt.status == "passed"
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)


def test_transfer_recovers_after_receipt_publication_without_any_callback(tmp_path, monkeypatch):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    publish = ledger.create_transfer_receipt

    def crash(receipt):
        publish(receipt)
        raise RuntimeError("after_receipt")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "create_transfer_receipt", crash)
        with pytest.raises(RuntimeError, match="after_receipt"):
            runner.run(**_kwargs())
    history = ledger.controller_checkpoint_history(runner._identity("learning-run", "transfer-target"))
    assert _fresh(ledger, gateway, verifier, judge).run(**_kwargs())[0].status == "passed"
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    assert ledger.controller_checkpoint_history(runner._identity("learning-run", "transfer-target")) == history


def test_transfer_without_persisted_worker_result_stays_quarantined(tmp_path, monkeypatch):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)

    def crash(*_args):
        raise RuntimeError("before_result")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash)
        with pytest.raises(RuntimeError, match="before_result"):
            runner.run(**_kwargs())
    with pytest.raises(RSILearningError, match="rsi_resume_recovery_required"):
        _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 0, 0)


@pytest.mark.parametrize("stage", ["verifier", "judge"])
def test_uncertain_verifier_or_judge_is_not_repeated(tmp_path, monkeypatch, stage):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    original = Verifier.verify if stage == "verifier" else Judge.__call__

    def crash(self, *args):
        original(self, *args)
        raise RuntimeError("side_effect_unknown")

    with monkeypatch.context() as patch:
        patch.setattr(Verifier if stage == "verifier" else Judge, "verify" if stage == "verifier" else "__call__", crash)
        with pytest.raises(RuntimeError, match="side_effect_unknown"):
            runner.run(**_kwargs())
        # Keep the same component code identity as the original interrupted call.
        with pytest.raises(RSILearningError, match=f"rsi_transfer_{stage}_reconcile_required"):
            _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert gateway.calls == 1
    assert verifier.calls == 1
    assert judge.calls == (1 if stage == "judge" else 0)


@pytest.mark.parametrize("field", [
    "max_solver_invocations", "max_evaluator_invocations", "max_verifier_invocations", "max_transfer_invocations",
])
def test_transfer_budget_gates_all_stages_before_launch(tmp_path, field):
    runner, _ledger, gateway, verifier, judge = _runner(tmp_path)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        runner.run(**_kwargs(budget={field: 0}))
    assert (gateway.calls, verifier.calls, judge.calls) == (0, 0, 0)


def test_transfer_recovery_preserves_budget_and_absolute_deadline(tmp_path, monkeypatch):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100)
    budget = {"deadline_unix": 200, "max_solver_invocations": 1, "max_transfer_invocations": 1}
    save = ledger.save_episode_result

    def crash(request, result):
        save(request, result)
        raise RuntimeError("after_result")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash)
        with pytest.raises(RuntimeError, match="after_result"):
            runner.run(**_kwargs(budget=budget))
    internal = runner._identity("learning-run", "transfer-target")
    before = ledger.controller_checkpoint(internal)
    with pytest.raises(RSILearningError, match="rsi_resume_budget_drift"):
        runner.run(**_kwargs(budget=budget | {"deadline_unix": 300}))
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 201)
    with pytest.raises(RSILearningError, match="rsi_budget_exhausted"):
        runner.run(**_kwargs(budget=budget))
    assert ledger.controller_checkpoint(internal) == before
    assert before[1]["budget_state"]["consumed"]["solver_invocations"] == 1
    assert before[1]["budget_state"]["consumed"]["transfer_invocations"] == 1
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 0, 0)


def test_transfer_rejects_pins_and_component_configuration_drift(tmp_path):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    runner.run(**_kwargs())
    with pytest.raises(RSILearningError, match="rsi_transfer_fingerprint_drift"):
        runner.run(**_kwargs(environment_sha256="b" * 64))
    with pytest.raises(RSILearningError, match="rsi_transfer_fingerprint_drift"):
        _fresh(ledger, gateway, Verifier(version=2), judge).run(**_kwargs())
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)


def test_transfer_lock_rejects_concurrent_duplicate(tmp_path):
    runner, ledger, gateway, _verifier, _judge = _runner(tmp_path)
    ready, release = threading.Event(), threading.Event()

    def hold():
        with ledger.controller_lock(runner._identity("learning-run", "transfer-target")):
            ready.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert ready.wait(timeout=5)
        with pytest.raises(RSILearningError, match="rsi_controller_busy"):
            runner.run(**_kwargs())
    finally:
        release.set()
        thread.join(timeout=5)
    assert gateway.calls == 0


@pytest.mark.parametrize("status", ["failed", "unknown", "cancelled"])
def test_permissive_judge_cannot_pass_unverified_terminal_worker(status):
    runner = FrozenMemoryTransferRunner(
        Gateway(status), target_judge=lambda _execution: (True, "untrusted acceptance"),
    )
    receipt, execution = runner.run(**_kwargs())
    assert not execution.passed
    assert receipt.status == ("unknown" if status == "unknown" else "failed")


def test_ready_receipt_finalizes_after_deadline_without_repeating_callbacks(tmp_path, monkeypatch):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100)
    budget = {"deadline_unix": 200, "max_solver_invocations": 1, "max_transfer_invocations": 1}

    def crash(_receipt):
        raise RuntimeError("before_receipt_publication")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "create_transfer_receipt", crash)
        with pytest.raises(RuntimeError, match="before_receipt_publication"):
            runner.run(**_kwargs(budget=budget))
    internal = runner._identity("learning-run", "transfer-target")
    before = ledger.controller_checkpoint(internal)[1]["budget_state"]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 201)
    first = _fresh(ledger, gateway, verifier, judge).run(**_kwargs(budget=budget))
    history = ledger.controller_checkpoint_history(internal)
    assert first[0].status == "passed"
    assert _fresh(ledger, gateway, verifier, judge).run(**_kwargs(budget=budget)) == first
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
    assert ledger.controller_checkpoint(internal)[1]["budget_state"] == before
    assert ledger.controller_checkpoint_history(internal) == history


def test_settled_worker_cannot_silently_rewrite_published_unknown_transfer(tmp_path):
    runner, ledger, gateway, verifier, judge = _runner(tmp_path, "unknown")
    receipt, execution = runner.run(**_kwargs())
    head = ledger.get_episode(execution.episode.episode_id)
    ledger.reconcile_episode(
        head.logical_id, worker_state="failed", expected_record_sha256=head.record_sha256,
        evidence={"reconciliation": {"source": "explicit-worker-exit-confirmed"}},
    )
    with pytest.raises(RSILearningError, match="rsi_transfer_unknown_receipt_reconcile_required"):
        _fresh(ledger, gateway, verifier, judge).run(**_kwargs())
    assert ledger.get_transfer("learning-run", "transfer-target").payload == receipt.to_dict()
    assert (gateway.calls, verifier.calls, judge.calls) == (1, 1, 1)
