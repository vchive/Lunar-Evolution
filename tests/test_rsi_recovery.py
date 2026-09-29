"""Failure-window and identity checks for the durable RSI controller."""
import hashlib
import multiprocessing
import sqlite3
from dataclasses import replace

import pytest

from lunar_evolution.rsi_controller import DeterministicCurriculum, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, LocalExactVerifier, SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_recovery import DurableLearningRun
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
PINS = {"contract_sha256": HEX, "evaluator_sha256": HEX, "environment_sha256": HEX, "solver_id": "mock"}


class Gateway:
    def __init__(self, statuses=(), *, crash=False):
        self.statuses = list(statuses)
        self.requests = []
        self.crash = crash

    def fingerprint(self):
        return "b" * 64

    def run(self, request):
        self.requests.append(request)
        if self.crash:
            raise RuntimeError("process interrupted")
        status = self.statuses.pop(0) if self.statuses else "completed"
        return DeterministicMockSolver(terminal_status=status).run(request)


def judge_after_practice(execution):
    return execution.episode.wave > 0, "gap"


def controller(tmp_path, gateway, **kwargs):
    return RSILearningController(gateway, ledger=RSILedger(tmp_path / "rsi.db"), **kwargs)


def test_completed_drs_idempotently_restores_results_and_memory(tmp_path):
    first_gateway = Gateway()
    first = controller(tmp_path, first_gateway, target_judge=judge_after_practice)
    result = first.run_drs(run_id="drs", **PINS, max_practice_rounds=1, max_target_attempts=2)
    assert len(first_gateway.requests) == 3
    assert len(result.memory_snapshot.items) == 1
    second_gateway = Gateway(crash=True)
    second = controller(tmp_path, second_gateway, target_judge=judge_after_practice)
    resumed = second.run_drs(run_id="drs", **PINS, max_practice_rounds=1, max_target_attempts=2)
    assert resumed == result
    assert second_gateway.requests == []
    assert second.resume(run_id="drs") == result


def test_uncertain_launch_is_not_reissued_until_evidence_reconciliation(tmp_path):
    gateway = Gateway(crash=True)
    original = controller(tmp_path, gateway)
    with pytest.raises(RuntimeError, match="interrupted"):
        original.run_drs(run_id="crashed", **PINS)
    resumed_gateway = Gateway(crash=True)
    resumed = controller(tmp_path, resumed_gateway)
    result = resumed.resume(run_id="crashed")
    assert result.status == "unknown"
    assert resumed_gateway.requests == []
    request = gateway.requests[0]
    head = resumed.ledger.get(request.episode_id)
    result = resumed.reconcile_episode(
        run_id="crashed", episode_id=request.episode_id,
        result=DeterministicMockSolver().run(request), expected_record_sha256=head.record_sha256,
    )
    assert result.status == "completed"
    assert resumed_gateway.requests == []


def test_unknown_practice_reconciliation_continues_original_target_and_commits_once(tmp_path):
    gateway = Gateway(("completed", "unknown"))
    first = controller(tmp_path, gateway, target_judge=judge_after_practice)
    result = first.run_drs(run_id="unknown", **PINS, max_practice_rounds=1, max_target_attempts=2)
    assert result.status == "unknown"
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    resumed_gateway = Gateway()
    second = controller(tmp_path, resumed_gateway, target_judge=judge_after_practice)
    assert second.resume(run_id="unknown").status == "unknown"
    assert resumed_gateway.requests == []
    request = gateway.requests[-1]
    evidence = DeterministicMockSolver().run(request)
    head = second.ledger.get(request.episode_id)
    done = second.reconcile_episode(run_id="unknown", episode_id=request.episode_id,
                                    result=evidence, expected_record_sha256=head.record_sha256)
    assert done.status == "completed"
    assert len(done.memory_snapshot.items) == 1
    assert [r.episode_id for r in resumed_gateway.requests] == ["unknown-target-1"]
    head = second.ledger.get(request.episode_id)
    assert second.reconcile_episode(run_id="unknown", episode_id=request.episode_id,
                                    result=evidence, expected_record_sha256=head.record_sha256) == done


@pytest.mark.parametrize("status", ["failed", "timed_out", "abandoned", "cancelled"])
def test_persisted_unknown_reconciles_to_terminal_failure_without_replay(tmp_path, status):
    gateway = Gateway(("unknown",))
    instance = controller(tmp_path, gateway)
    initial = instance.run_drs(run_id="unknown-terminal", **PINS,
                               max_target_attempts=1, max_practice_rounds=0)
    assert initial.status == "unknown"
    request = gateway.requests[0]
    head = instance.ledger.get(request.episode_id)
    assert head.state == "unknown"
    result = instance.reconcile_episode(
        run_id="unknown-terminal", episode_id=request.episode_id,
        result=DeterministicMockSolver(terminal_status=status).run(request),
        expected_record_sha256=head.record_sha256,
    )
    assert result.status == "failed"
    assert instance.ledger.get(request.episode_id).state == status
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert instance.resume(run_id="unknown-terminal") == result
    assert len(gateway.requests) == 1


def test_terminal_result_survives_verifier_crash_without_automatic_verifier_retry(tmp_path):
    class Verifier(LocalExactVerifier):
        crash = True
        calls = 0

        def verify(self, *args):
            self.calls += 1
            if self.crash:
                raise RuntimeError("verifier interrupted")
            return super().verify(*args)

    gateway = Gateway()
    verifier = Verifier()
    first = controller(tmp_path, gateway, verifier=verifier)
    with pytest.raises(RuntimeError, match="verifier interrupted"):
        first.run_drs(run_id="verification", **PINS)
    verifier.crash = False
    resumed = controller(tmp_path, Gateway(crash=True), verifier=verifier).resume(run_id="verification")
    assert resumed.status == "unknown"
    assert verifier.calls == 1
    assert len(gateway.requests) == 1


def test_memory_record_checkpoint_gap_recovers_without_duplicate_memory(tmp_path, monkeypatch):
    gateway = Gateway()
    first = controller(tmp_path, gateway, target_judge=judge_after_practice)
    original = DurableLearningRun._save
    crashed = False

    def fail_once(self):
        nonlocal crashed
        if self.state["commits"] and not crashed:
            crashed = True
            raise RuntimeError("memory checkpoint interrupted")
        return original(self)

    monkeypatch.setattr(DurableLearningRun, "_save", fail_once)
    with pytest.raises(RuntimeError, match="memory checkpoint interrupted"):
        first.run_drs(run_id="memory", **PINS, max_practice_rounds=1, max_target_attempts=2)
    monkeypatch.setattr(DurableLearningRun, "_save", original)
    second_gateway = Gateway()
    result = controller(tmp_path, second_gateway, target_judge=judge_after_practice).resume(run_id="memory")
    assert result.status == "completed"
    assert len(result.memory_snapshot.items) == 1
    assert [r.episode_id for r in second_gateway.requests] == ["memory-target-1"]


def test_brs_quarantines_successes_until_unknown_child_is_settled(tmp_path):
    class OrdinalGateway(Gateway):
        def run(self, request):
            self.requests.append(request)
            return DeterministicMockSolver(
                terminal_status="unknown" if request.episode_id.endswith("-1") else "completed",
            ).run(request)

    gateway = OrdinalGateway()
    first = controller(tmp_path, gateway)
    target = first._target_episode("brs", "seed", PINS, 0)
    decisions = [DeterministicCurriculum().choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i)
                 for i in range(2)]
    result = first.run_brs(run_id="brs", **PINS, practices=decisions)
    assert result.status == "unknown"
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert first.ledger.controller_checkpoint("brs")[1]["quarantined"] == ["brs-practice-0-0"]
    second_gateway = OrdinalGateway()
    second = controller(tmp_path, second_gateway)
    assert second.resume(run_id="brs").status == "unknown"
    request = next(r for r in gateway.requests if r.episode_id.endswith("-1"))
    head = second.ledger.get(request.episode_id)
    result = second.reconcile_episode(run_id="brs", episode_id=request.episode_id,
                                      result=DeterministicMockSolver().run(request),
                                      expected_record_sha256=head.record_sha256)
    assert result.status == "completed"
    assert [item.trigger for item in result.memory_snapshot.items] == ["gap-0", "gap-1"]
    assert second_gateway.requests == []
    assert second.ledger.controller_checkpoint("brs")[1]["quarantined"] == []


@pytest.mark.parametrize("pin", ["contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id"])
def test_resume_rejects_identity_drift_before_gateway(tmp_path, pin):
    first = controller(tmp_path, Gateway(("unknown",)))
    first.run_drs(run_id="drift", **PINS)
    gateway = Gateway(crash=True)
    second = controller(tmp_path, gateway)
    changed = "other" if pin == "solver_id" else "c" * 64
    with pytest.raises(RSILearningError, match=f"rsi_resume_{pin}_drift"):
        second.resume(run_id="drift", **{pin: changed})
    assert gateway.requests == []


def test_resume_rejects_settings_budget_judge_and_actor_drift(tmp_path):
    first = controller(tmp_path, Gateway(("unknown",)), solver_settings={"temperature": 0})
    first.run_drs(run_id="settings", **PINS, budget={"calls": 1})
    with pytest.raises(RSILearningError, match="solver_settings_drift"):
        controller(tmp_path, Gateway(), solver_settings={"temperature": 1}).resume(run_id="settings")
    with pytest.raises(RSILearningError, match="configuration_drift"):
        first.run_drs(run_id="settings", **PINS, budget={"calls": 2})
    with pytest.raises(RSILearningError, match="target_judge_fingerprint_drift"):
        controller(tmp_path, Gateway(), solver_settings={"temperature": 0},
                   target_judge=judge_after_practice).resume(run_id="settings")
    with pytest.raises(RSILearningError, match="actor_fingerprint_drift"):
        controller(tmp_path, Gateway(), solver_settings={"temperature": 0},
                   actor_fingerprint="c" * 64).resume(run_id="settings")


def test_reconcile_rejects_forged_request_stale_cas_and_missing_receipts(tmp_path):
    gateway = Gateway(("unknown",))
    instance = controller(tmp_path, gateway)
    instance.run_drs(run_id="evidence", **PINS)
    request = gateway.requests[0]
    evidence = DeterministicMockSolver().run(request)
    head = instance.ledger.get(request.episode_id)
    for candidate, expected, error in (
        (replace(evidence, request_sha256="d" * 64), head.record_sha256, "identity_mismatch"),
        (evidence, "d" * 64, "parent_conflict"),
        (replace(evidence, candidate_receipt_sha256=None), head.record_sha256, "evidence_missing"),
    ):
        with pytest.raises(RSILearningError, match=error):
            instance.reconcile_episode(run_id="evidence", episode_id=request.episode_id,
                                        result=candidate, expected_record_sha256=expected)
    assert instance.resume(run_id="evidence").status == "unknown"


@pytest.mark.parametrize("change", ["stage_only", "erase_result", "erase_entry"])
def test_resume_rejects_checkpoint_stage_that_would_reopen_unknown_launch(tmp_path, change):
    first_gateway = Gateway(("unknown",))
    first = controller(tmp_path, first_gateway)
    result = first.run_drs(run_id="stage-gate", **PINS, max_practice_rounds=0, max_target_attempts=1)
    assert result.status == "unknown"
    version, state = first.ledger.controller_checkpoint("stage-gate")
    entry = state["episodes"]["stage-gate-target-0"]
    assert entry["stage"] == "unknown" and entry["result"]["status"] == "unknown"
    entry["stage"] = "planned"
    if change == "erase_result":
        entry["result"] = None
        entry["episode"] = None
    elif change == "erase_entry":
        del state["episodes"]["stage-gate-target-0"]
    with first.ledger.controller_lock("stage-gate"):
        first.ledger.write_controller_checkpoint("stage-gate", state, expected_sha256=version)

    resumed_gateway = Gateway(crash=True)
    expected_error = "episode_checkpoint_gap" if change == "erase_entry" else "episode_stage_invalid"
    with pytest.raises(RSILearningError, match=expected_error):
        controller(tmp_path, resumed_gateway).resume(run_id="stage-gate")
    assert resumed_gateway.requests == []


def test_resume_can_launch_planned_episode_with_no_retained_launch(tmp_path, monkeypatch):
    first_gateway = Gateway()
    first = controller(tmp_path, first_gateway)
    original = DurableLearningRun._save

    def stop_before_launch_checkpoint(self):
        if any(entry["stage"] == "launched" for entry in self.state["episodes"].values()):
            raise RuntimeError("before durable launch")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(DurableLearningRun, "_save", stop_before_launch_checkpoint)
        with pytest.raises(RuntimeError, match="before durable launch"):
            first.run_drs(run_id="planned", **PINS, max_practice_rounds=0, max_target_attempts=1)
    assert first_gateway.requests == []
    assert first.ledger.get("planned-target-0") is None
    second_gateway = Gateway()
    second = controller(tmp_path, second_gateway)
    assert second.resume(run_id="planned").status == "completed"
    assert len(second_gateway.requests) == 1
    second.resume(run_id="planned")
    assert len(second_gateway.requests) == 1


def test_controller_lock_blocks_second_owner_and_checkpoint_corruption(tmp_path):
    instance = controller(tmp_path, Gateway())
    with instance.ledger.controller_lock("locked"), pytest.raises(RSILearningError, match="controller_busy"):
        instance.run_drs(run_id="locked", **PINS)
    instance.run_drs(run_id="corrupt", **PINS)
    with sqlite3.connect(instance.ledger.database) as connection:
        connection.execute("UPDATE rsi_controller_journal SET payload = '{}' WHERE run_id = 'corrupt' AND revision = 0")
    with pytest.raises(RSILearningError, match="checkpoint_corrupt"):
        instance.resume(run_id="corrupt")


def test_durable_request_can_be_reconstructed_for_external_reconciliation(tmp_path):
    instance = controller(tmp_path, Gateway(("unknown",)))
    instance.run_drs(run_id="request", **PINS)
    checkpoint = instance.ledger.controller_checkpoint("request")[1]
    request = SolverRequest.from_dict(checkpoint["episodes"]["request-target-0"]["request"])
    assert request.digest() == instance.ledger.get("request-target-0").request_sha256


def test_verifier_append_checkpoint_gap_reuses_existing_decision(tmp_path, monkeypatch):
    class Verifier(LocalExactVerifier):
        calls = 0

        def verify(self, *args):
            self.calls += 1
            return super().verify(*args)

    verifier = Verifier()
    original = DurableLearningRun._save
    crashed = False

    def fail_once(self):
        nonlocal crashed
        has_verifier = any(entry.get("episode") and entry["episode"].get("verifier")
                           for entry in self.state["episodes"].values())
        if has_verifier and not crashed:
            crashed = True
            raise RuntimeError("verified checkpoint interrupted")
        return original(self)

    monkeypatch.setattr(DurableLearningRun, "_save", fail_once)
    with pytest.raises(RuntimeError, match="verified checkpoint interrupted"):
        controller(tmp_path, Gateway(), verifier=verifier).run_drs(run_id="verified", **PINS)
    monkeypatch.setattr(DurableLearningRun, "_save", original)
    resumed = controller(tmp_path, Gateway(crash=True), verifier=verifier).resume(run_id="verified")
    assert resumed.status == "completed"
    assert verifier.calls == 1


def test_brs_partial_ordered_commit_recovers_from_frozen_parent(tmp_path, monkeypatch):
    first = controller(tmp_path, Gateway())
    target = first._target_episode("merge", "seed", PINS, 0)
    decisions = [DeterministicCurriculum().choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i)
                 for i in range(3)]
    original = DurableLearningRun._save
    crashed = False

    def fail_after_commit(self):
        nonlocal crashed
        result = original(self)
        if len(self.state["commits"]) == 1 and not crashed:
            crashed = True
            raise RuntimeError("first merge committed")
        return result

    monkeypatch.setattr(DurableLearningRun, "_save", fail_after_commit)
    with pytest.raises(RuntimeError, match="first merge committed"):
        first.run_brs(run_id="merge", **PINS, practices=decisions)
    monkeypatch.setattr(DurableLearningRun, "_save", original)
    gateway = Gateway(crash=True)
    done = controller(tmp_path, gateway).resume(run_id="merge")
    assert done.status == "completed"
    assert [item.trigger for item in done.memory_snapshot.items] == ["gap-0", "gap-1", "gap-2"]
    assert gateway.requests == []
    assert {execution.episode.memory_snapshot_sha256 for execution in done.practice_episodes} == {
        EMPTY_MEMORY_SNAPSHOT.digest(),
    }


def test_checkpoint_created_before_run_record_is_recoverable(tmp_path, monkeypatch):
    instance = controller(tmp_path, Gateway())
    original = instance.ledger.create_run
    monkeypatch.setattr(instance.ledger, "create_run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("create interrupted")))
    with pytest.raises(RuntimeError, match="create interrupted"):
        instance.run_drs(run_id="create", **PINS)
    monkeypatch.setattr(instance.ledger, "create_run", original)
    assert instance.resume(run_id="create").status == "completed"


def test_resume_rejects_deleted_committed_memory_evidence(tmp_path):
    instance = controller(tmp_path, Gateway(), target_judge=judge_after_practice)
    instance.run_drs(run_id="memory-evidence", **PINS, max_practice_rounds=1, max_target_attempts=2)
    with sqlite3.connect(instance.ledger.database) as connection:
        connection.execute("DELETE FROM rsi_records WHERE kind = 'memory'")
    with pytest.raises(RSILearningError, match="snapshot_evidence_mismatch"):
        instance.resume(run_id="memory-evidence")


def _hold_controller_lock(path, ready, release):
    with RSILedger(path).controller_lock("multiprocess"):
        ready.set()
        release.wait(5)


def test_run_lock_rejects_independent_process_owner(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_hold_controller_lock, args=(tmp_path / "rsi.db", ready, release))
    process.start()
    try:
        assert ready.wait(5)
        with pytest.raises(RSILearningError, match="controller_busy"):
            controller(tmp_path, Gateway()).run_drs(run_id="multiprocess", **PINS)
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()
    assert process.exitcode == 0


@pytest.mark.parametrize("replacement", ["symlink", "hardlink", "regular"])
def test_replaced_controller_lock_blocks_checkpoint_and_gateway(tmp_path, monkeypatch, replacement):
    instance = controller(tmp_path, Gateway())
    original = instance.ledger.write_controller_checkpoint
    mutated = False

    def replace_after_first(*args, **kwargs):
        nonlocal mutated
        answer = original(*args, **kwargs)
        if not mutated:
            mutated = True
            lock = tmp_path / "rsi.db.controller-locks" / hashlib.sha256(b"lock-replace").hexdigest()
            moved = tmp_path / "old-lock"
            lock.rename(moved)
            if replacement == "symlink":
                lock.symlink_to(moved)
            elif replacement == "hardlink":
                lock.hardlink_to(moved)
                (tmp_path / "extra-lock-link").hardlink_to(moved)
            else:
                lock.write_text("")
        return answer

    monkeypatch.setattr(instance.ledger, "write_controller_checkpoint", replace_after_first)
    with pytest.raises(RSILearningError, match="lock_identity_changed"):
        instance.run_drs(run_id="lock-replace", **PINS)
    assert instance.gateway.requests == []


def test_named_symlink_lock_cannot_be_acquired(tmp_path):
    instance = controller(tmp_path, Gateway())
    lock_dir = tmp_path / "rsi.db.controller-locks"
    lock_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("preserve")
    (lock_dir / hashlib.sha256(b"link").hexdigest()).symlink_to(target)
    with pytest.raises(RSILearningError, match="lock_invalid"):
        instance.run_drs(run_id="link", **PINS)
    assert target.read_text() == "preserve"


def test_retained_evidence_reopened_without_solver_or_verifier_rerun(tmp_path):
    class RetainedVerifier(LocalExactVerifier):
        def __init__(self):
            self.calls = 0
            self.retained_calls = 0
            self.missing = False

        def verify(self, *args):
            self.calls += 1
            return super().verify(*args)

        def validate_retained(self, episode, request, result, decision):
            self.retained_calls += 1
            if self.missing:
                raise RSILearningError("rsi_retained_receipt_missing")

    verifier = RetainedVerifier()
    instance = controller(tmp_path, Gateway(), verifier=verifier)
    instance.run_drs(run_id="retained", **PINS)
    calls = verifier.calls
    assert instance.resume(run_id="retained").status == "completed"
    assert verifier.calls == calls
    verifier.missing = True
    with pytest.raises(RSILearningError, match="retained_receipt_missing"):
        instance.resume(run_id="retained")
    assert verifier.calls == calls


def test_checkpoint_result_must_match_canonical_episode_evidence(tmp_path):
    instance = controller(tmp_path, Gateway())
    instance.run_drs(run_id="semantic", **PINS)
    version, state = instance.ledger.controller_checkpoint("semantic")
    state["episodes"]["semantic-target-0"]["result"]["candidate_receipt_sha256"] = "f" * 64
    with instance.ledger.controller_lock("semantic"):
        instance.ledger.write_controller_checkpoint("semantic", state, expected_sha256=version)
    with pytest.raises(RSILearningError, match="episode_result_mismatch"):
        instance.resume(run_id="semantic")


def test_historical_verified_episode_cannot_replace_newer_ledger_head(tmp_path):
    instance = controller(tmp_path, Gateway())
    result = instance.run_drs(run_id="old-head", **PINS)
    episode = result.target_attempts[0].episode
    newer = replace(episode, previous_record_sha256=episode.digest())
    instance.ledger.append_episode_record(newer)
    with pytest.raises(RSILearningError, match="ledger_head_conflict"):
        instance.resume(run_id="old-head")
