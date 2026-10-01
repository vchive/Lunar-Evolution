"""Local crash injection for the complete Feature 160 DRS/BRS recovery flow."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    DeterministicCurriculum,
    DeterministicMockSolver,
    LocalExactVerifier,
    RSILearningController,
    RSILearningError,
    RSILedger,
    RSIMemoryStore,
    RSIPracticeEpisode,
)

HEX = "a" * 64
PINS = {"contract_sha256": HEX, "evaluator_sha256": HEX,
        "environment_sha256": HEX, "solver_id": "mock"}


class FixtureCrash(RuntimeError):
    pass


class RecordingGateway:
    def __init__(self):
        self.requests = []
        self._lock = Lock()

    def rsi_fingerprint_config(self):
        return {"fixture": "durable-completed-v1"}

    def run(self, request):
        with self._lock:
            self.requests.append(request)
        return DeterministicMockSolver().run(request)


class RecordingVerifier(LocalExactVerifier):
    def __init__(self):
        self.calls = []

    def rsi_fingerprint_config(self):
        return {"fixture": "durable-local-exact-v1"}

    def verify(self, episode, request, result):
        self.calls.append(episode.episode_id)
        return super().verify(episode, request, result)


class JudgeAfterPractice:
    def rsi_fingerprint_config(self):
        return {"minimum_wave": 1}

    def __call__(self, execution):
        return execution.passed and execution.episode.wave >= 1, "practice the first target gap"


class BlockingGateway(RecordingGateway):
    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def rsi_fingerprint_config(self):
        return {"fixture": "blocking-durable-completed-v1"}

    def run(self, request):
        self.entered.set()
        assert self.release.wait(timeout=10)
        return super().run(request)


class UnknownFirstTargetGateway(RecordingGateway):
    def rsi_fingerprint_config(self):
        return {"target_zero": "unknown", "later_episodes": "completed"}

    def run(self, request):
        with self._lock:
            self.requests.append(request)
        status = "unknown" if request.episode_id.endswith("-target-0") else "completed"
        return DeterministicMockSolver(terminal_status=status).run(request)


class ConfigurableGateway(RecordingGateway):
    def __init__(self, configuration="original"):
        super().__init__()
        self.configuration = configuration

    def rsi_fingerprint_config(self):
        return {"configuration": self.configuration}


class ConfigurableVerifier(RecordingVerifier):
    def __init__(self, configuration="original"):
        super().__init__()
        self.configuration = configuration

    def rsi_fingerprint_config(self):
        return {"configuration": self.configuration}


class DeadlineAdvancingVerifier(RecordingVerifier):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def rsi_fingerprint_config(self):
        return {"fixture": "advance-clock-after-verification", "finished_at": 102.0}

    def verify(self, episode, request, result):
        decision = super().verify(episode, request, result)
        self.clock[0] = 102.0
        return decision


def controller(ledger, gateway, verifier=None):
    return RSILearningController(
        gateway, ledger=ledger, verifier=verifier or RecordingVerifier(),
        curriculum=DeterministicCurriculum(), target_judge=JudgeAfterPractice(),
    )


def resume(restarted, ledger, run_id):
    head = ledger.get_run(run_id)
    return restarted.resume(
        run_id, observed_fingerprints={"run_fingerprint": head.payload["fingerprints"]["run_fingerprint"]},
    )


def count_memory_commits(monkeypatch):
    commits = []
    original = RSIMemoryStore.commit

    def record_commit(self, **kwargs):
        commits.append(kwargs["memory"].memory_id)
        return original(self, **kwargs)

    monkeypatch.setattr(RSIMemoryStore, "commit", record_commit)
    return commits


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("crash_point", ["result", "verified"])
def test_drs_practice_crash_restores_memory_before_next_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paused: bool, crash_point: str,
):
    run_id = "durable-drs"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway, verifier = RecordingGateway(), RecordingVerifier()
    learner = controller(ledger, gateway, verifier)
    commits = count_memory_commits(monkeypatch)
    save_result = ledger.save_episode_result
    append_episode = ledger.append_episode_record

    def crash_after_practice_result(request, result):
        save_result(request, result)
        if crash_point == "result" and request.episode_id.endswith("-practice-0-0"):
            raise FixtureCrash("practice_evidence_persisted")

    def crash_after_verifier(episode, **kwargs):
        stored = append_episode(episode, **kwargs)
        if crash_point == "verified" and episode.episode_kind == "practice" and episode.verifier is not None:
            raise FixtureCrash("practice_evidence_persisted")
        return stored

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_practice_result)
        patch.setattr(ledger, "append_episode_record", crash_after_verifier)
        with pytest.raises(FixtureCrash, match="practice_evidence_persisted"):
            learner.run_drs(run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2)
    assert [request.episode_id for request in gateway.requests] == [
        f"{run_id}-target-0", f"{run_id}-practice-0-0",
    ]
    assert commits == []
    if paused:
        head = ledger.get_run(run_id)
        ledger.transition(run_id, state="paused", expected_record_sha256=head.record_sha256)

    reopened = RSILedger(ledger.database)
    result = resume(controller(reopened, gateway, verifier), reopened, run_id)

    assert result.status == "completed"
    assert [request.episode_id for request in gateway.requests] == [
        f"{run_id}-target-0", f"{run_id}-practice-0-0", f"{run_id}-target-1",
    ]
    assert commits == [f"memory-{run_id}-practice-0-0"]
    assert Counter(verifier.calls) == Counter(request.episode_id for request in gateway.requests)
    assert len(result.memory_snapshot.items) == 1
    assert result.target_attempts[-1].request.memory_snapshot_sha256 == result.memory_snapshot.digest()
    head = reopened.get_run(run_id)
    assert head.state == "completed"
    assert head.payload["budget_state"]["consumed"]["solver_invocations"] == 3
    before = reopened.history(run_id)
    again = resume(controller(RSILedger(ledger.database), gateway, verifier), reopened, run_id)
    assert again.memory_snapshot == result.memory_snapshot
    assert reopened.history(run_id) == before
    assert len(gateway.requests) == 3
    assert len(commits) == 1


def test_brs_memory_publication_crash_resumes_ordinal_merge_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "durable-brs"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway, verifier = RecordingGateway(), RecordingVerifier()
    learner = controller(ledger, gateway, verifier)
    target = learner._target_episode(run_id, f"{run_id}-target-seed", PINS, 0)
    decisions = [learner.curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(3)]
    commits = count_memory_commits(monkeypatch)
    publish = ledger.create_memory_snapshot

    def crash_after_memory_publication(snapshot):
        result = publish(snapshot)
        if len(snapshot.items) == 1:
            raise FixtureCrash("first_memory_persisted")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "create_memory_snapshot", crash_after_memory_publication)
        with pytest.raises(FixtureCrash, match="first_memory_persisted"):
            learner.run_brs(run_id=run_id, **PINS, practices=decisions, max_workers=3)
    episode_ids = tuple(f"{run_id}-practice-0-{i}" for i in range(3))
    assert {request.episode_id for request in gateway.requests} == set(episode_ids)
    assert all(ledger.get_episode(episode_id).state == "completed" for episode_id in episode_ids)

    reopened = RSILedger(ledger.database)
    recovered = resume(controller(reopened, gateway, verifier), reopened, run_id)

    assert recovered.status == "completed"
    assert [item.trigger for item in recovered.memory_snapshot.items] == ["gap-0", "gap-1", "gap-2"]
    assert commits == [f"memory-{episode_id}" for episode_id in episode_ids]
    assert Counter(verifier.calls) == Counter(episode_ids)
    assert len(gateway.requests) == 3
    assert reopened.get_run(run_id).payload["budget_state"]["consumed"]["solver_invocations"] == 3
    terminal = reopened.history(run_id)
    again = resume(controller(RSILedger(ledger.database), gateway, verifier), reopened, run_id)
    assert again.memory_snapshot == recovered.memory_snapshot
    assert reopened.history(run_id) == terminal
    assert len(commits) == 3
    assert len(gateway.requests) == 3


@pytest.mark.parametrize("budget", [
    {"max_solver_invocations": 0}, {"max_target_attempts": 0},
    {"max_evaluator_invocations": 0}, {"max_verifier_invocations": 0},
    {"deadline_unix": 1.0},
])
def test_exhausted_budget_stops_before_first_launch(tmp_path: Path, budget):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    result = controller(ledger, gateway).run_drs(
        run_id="empty-budget", **PINS, max_practice_rounds=1, max_target_attempts=2, budget=budget,
    )
    assert result.status == "budget_exhausted"
    assert ledger.get_run("empty-budget").state == "budget_exhausted"
    assert ledger.episode_ids_for_run("empty-budget") == ()
    assert gateway.requests == []
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT


def test_expired_resume_deadline_cannot_launch_practice_or_reset_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    learner = controller(ledger, gateway)
    commits = count_memory_commits(monkeypatch)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    save_result = ledger.save_episode_result

    def crash_after_target_result(request, result):
        save_result(request, result)
        raise FixtureCrash("target_result_persisted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_target_result)
        with pytest.raises(FixtureCrash, match="target_result_persisted"):
            learner.run_drs(
                run_id="expired-resume", **PINS, max_practice_rounds=1,
                max_target_attempts=2, budget={"deadline_unix": 101.0},
            )
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 102.0)
    reopened = RSILedger(ledger.database)

    result = resume(controller(reopened, gateway), reopened, "expired-resume")

    assert result.status == "budget_exhausted"
    assert len(gateway.requests) == 1
    assert commits == []
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    head = reopened.get_run("expired-resume")
    assert head.state == "budget_exhausted"
    assert head.payload["budget_state"]["planned"]["deadline_unix"] == 101.0
    assert head.payload["budget_state"]["consumed"]["solver_invocations"] == 1


def test_unknown_practice_without_result_blocks_retry_and_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    learner = controller(ledger, gateway)
    commits = count_memory_commits(monkeypatch)
    save_result = ledger.save_episode_result

    def lose_practice_result(request, result):
        if request.episode_id.endswith("-practice-0-0"):
            raise FixtureCrash("practice_result_lost")
        save_result(request, result)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", lose_practice_result)
        with pytest.raises(FixtureCrash, match="practice_result_lost"):
            learner.run_drs(run_id="unknown-practice", **PINS, max_practice_rounds=1, max_target_attempts=2)
    head = ledger.get_episode("unknown-practice-practice-0-0")
    unknown = RSIPracticeEpisode.from_dict(head.payload).transition("unknown", terminal_reason="lost_worker")
    ledger.append_episode_record(unknown, expected_record_sha256=head.record_sha256)
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        resume(controller(RSILedger(ledger.database), gateway), ledger, "unknown-practice")
    assert len(gateway.requests) == 2
    assert commits == []
    assert ledger.get_episode(unknown.episode_id).state == "unknown"
    assert ledger.episode_result(unknown.episode_id) is None


def test_unknown_brs_child_blocks_whole_wave_memory_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "brs-unknown-child"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    learner = controller(ledger, gateway)
    target = learner._target_episode(run_id, f"{run_id}-target-seed", PINS, 0)
    decisions = [learner.curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(2)]
    commits = count_memory_commits(monkeypatch)
    save_result = ledger.save_episode_result

    def lose_second_result(request, result):
        if request.episode_id.endswith("-practice-0-1"):
            raise FixtureCrash("second_child_result_lost")
        save_result(request, result)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", lose_second_result)
        with pytest.raises(FixtureCrash, match="second_child_result_lost"):
            learner.run_brs(run_id=run_id, **PINS, practices=decisions, max_workers=2)
    assert ledger.get_episode(f"{run_id}-practice-0-0").state == "completed"
    head = ledger.get_episode(f"{run_id}-practice-0-1")
    unknown = RSIPracticeEpisode.from_dict(head.payload).transition("unknown", terminal_reason="lost_child")
    ledger.append_episode_record(unknown, expected_record_sha256=head.record_sha256)

    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        resume(controller(RSILedger(ledger.database), gateway), ledger, run_id)

    assert len(gateway.requests) == 2
    assert commits == []
    assert ledger.episode_result(unknown.episode_id) is None
    assert ledger.get_episode(unknown.episode_id).state == "unknown"


@pytest.mark.parametrize("competing_action", ["resume", "run"])
def test_live_run_excludes_competing_controller(
    tmp_path: Path, competing_action: str,
):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = BlockingGateway()
    learner = controller(ledger, gateway)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(learner.run_drs, run_id="live-run", **PINS, max_practice_rounds=0, max_target_attempts=1)
        try:
            assert gateway.entered.wait(timeout=5)
            reopened = RSILedger(ledger.database)
            other = controller(reopened, gateway)
            with pytest.raises(RSILearningError, match="rsi_controller_busy"):
                if competing_action == "resume":
                    resume(other, reopened, "live-run")
                else:
                    other.run_drs(run_id="live-run", **PINS, max_practice_rounds=0, max_target_attempts=1)
        finally:
            gateway.release.set()
        assert pending.result(timeout=10).status == "failed"
    assert len(gateway.requests) == 1


def test_explicit_unknown_reconcile_resumes_without_rewriting_worker_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "explicit-unknown-reconcile"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = UnknownFirstTargetGateway()
    commits = count_memory_commits(monkeypatch)
    initial = controller(ledger, gateway).run_drs(
        run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
        budget={"max_unknown_retries": 1},
    )
    assert initial.status == "unknown"
    episode_id = f"{run_id}-target-0"
    request_before, result_before = ledger.episode_result(episode_id)
    assert result_before.status == "unknown"
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        resume(controller(RSILedger(ledger.database), gateway), ledger, run_id)
    head = ledger.get_episode(episode_id)
    settled = ledger.reconcile_episode(
        episode_id, worker_state="failed", expected_record_sha256=head.record_sha256,
        evidence={"reconciliation": {"source": "local_fixture_exit_observation", "process_exited": True}},
    )
    assert settled.state == "failed"

    reopened = RSILedger(ledger.database)
    recovered = resume(controller(reopened, gateway), reopened, run_id)

    assert recovered.status == "completed"
    assert [request.episode_id for request in gateway.requests] == [
        episode_id, f"{run_id}-practice-0-0", f"{run_id}-target-1",
    ]
    assert reopened.episode_result(episode_id) == (request_before, result_before)
    assert reopened.get_episode(episode_id).state == "failed"
    assert len(reopened.episode_reconciliation(episode_id)) == 1
    assert commits == [f"memory-{run_id}-practice-0-0"]
    assert reopened.get_run(run_id).payload["budget_state"]["consumed"]["unknown_retries"] == 1
    history = reopened.history(run_id)
    assert resume(controller(RSILedger(ledger.database), gateway), reopened, run_id).status == "completed"
    assert reopened.history(run_id) == history
    assert len(gateway.requests) == 3


def test_persisted_terminal_checkpoint_wins_over_expired_resume_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "terminal-before-deadline"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway, verifier = RecordingGateway(), RecordingVerifier()
    learner = controller(ledger, gateway, verifier)
    commits = count_memory_commits(monkeypatch)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    transition = ledger.transition

    def crash_before_terminal_run_head(logical_id, **kwargs):
        if logical_id == run_id and kwargs["state"] == "completed":
            raise FixtureCrash("terminal_checkpoint_already_persisted")
        return transition(logical_id, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "transition", crash_before_terminal_run_head)
        with pytest.raises(FixtureCrash, match="terminal_checkpoint_already_persisted"):
            learner.run_drs(
                run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
                budget={"deadline_unix": 101.0},
            )
    checkpoint_before = ledger.controller_checkpoint(run_id)
    assert checkpoint_before[1]["status"] == "completed"
    assert ledger.get_run(run_id).state == "running"
    assert len(gateway.requests) == len(verifier.calls) == 3
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 102.0)
    reopened = RSILedger(ledger.database)
    old_fingerprint = reopened.get_run(run_id).payload["fingerprints"]["run_fingerprint"]

    recovered = controller(reopened, gateway, verifier).resume(
        run_id, now=102.0, observed_fingerprints={"run_fingerprint": old_fingerprint},
    )

    assert recovered.status == "completed"
    assert reopened.get_run(run_id).state == "completed"
    assert reopened.controller_checkpoint(run_id) == checkpoint_before
    assert reopened.get_run(run_id).payload["budget_state"] == checkpoint_before[1]["budget_state"]
    assert len(gateway.requests) == len(verifier.calls) == 3
    assert commits == [f"memory-{run_id}-practice-0-0"]


@pytest.mark.parametrize("changed_component", ["solver", "verifier"])
def test_supplied_old_fingerprint_cannot_hide_current_component_config_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_component: str,
):
    run_id = "component-config-drift"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway, verifier = ConfigurableGateway(), ConfigurableVerifier()
    save_result = ledger.save_episode_result

    def crash_after_target_result(request, result):
        save_result(request, result)
        raise FixtureCrash("target_result_persisted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_target_result)
        with pytest.raises(FixtureCrash, match="target_result_persisted"):
            controller(ledger, gateway, verifier).run_drs(
                run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
            )
    head_before = ledger.get_run(run_id)
    checkpoint_before = ledger.controller_checkpoint(run_id)
    episode_before = ledger.get_episode(f"{run_id}-target-0")
    next_gateway = ConfigurableGateway("changed") if changed_component == "solver" else gateway
    next_verifier = ConfigurableVerifier("changed") if changed_component == "verifier" else verifier

    with pytest.raises(RSILearningError, match="rsi_resume_fingerprint_drift"):
        controller(RSILedger(ledger.database), next_gateway, next_verifier).resume(
            run_id, observed_fingerprints={"run_fingerprint": head_before.payload["fingerprints"]["run_fingerprint"]},
        )

    assert ledger.get_run(run_id) == head_before
    assert ledger.controller_checkpoint(run_id) == checkpoint_before
    assert ledger.get_episode(episode_before.logical_id) == episode_before
    assert len(gateway.requests) == 1
    assert next_gateway.requests == ([] if changed_component == "solver" else gateway.requests)
    assert next_verifier.calls == []


def test_run_creation_crash_before_first_checkpoint_preserves_plan_and_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "created-before-checkpoint"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    learner = controller(ledger, gateway)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.0)
    write_checkpoint = ledger.write_controller_checkpoint

    def crash_before_initial_checkpoint(requested_run_id, state, **kwargs):
        if requested_run_id == run_id and state["schema_version"] == "2":
            raise FixtureCrash("initial_checkpoint_not_written")
        return write_checkpoint(requested_run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "write_controller_checkpoint", crash_before_initial_checkpoint)
        with pytest.raises(FixtureCrash, match="initial_checkpoint_not_written"):
            learner.run_drs(
                run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
                budget={"deadline_unix": 101.0},
            )
    original = ledger.get_run(run_id)
    assert original is not None
    assert original.payload["plan"]["max_target_attempts"] == 2
    assert ledger.controller_checkpoint(run_id) is None
    assert ledger.episode_ids_for_run(run_id) == ()
    assert gateway.requests == []
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: 100.5)
    reopened = RSILedger(ledger.database)

    result = resume(controller(reopened, gateway), reopened, run_id)

    assert result.status == "completed"
    assert [request.episode_id for request in gateway.requests] == [
        f"{run_id}-target-0", f"{run_id}-practice-0-0", f"{run_id}-target-1",
    ]
    head = reopened.get_run(run_id)
    assert head.payload["plan"] == original.payload["plan"]
    assert head.payload["budget"]["deadline_unix"] == 101.0
    assert head.payload["budget_state"]["planned"]["deadline_unix"] == 101.0
    assert head.payload["budget_state"]["consumed"]["solver_invocations"] == 3


def test_brs_resume_rechecks_deadline_before_each_pending_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "pending-verifiers"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    clock = [100.0]
    verifier = DeadlineAdvancingVerifier(clock)
    learner = controller(ledger, gateway, verifier)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: clock[0])
    target = learner._target_episode(run_id, f"{run_id}-target-seed", PINS, 0)
    decisions = [learner.curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i) for i in range(2)]
    save_result = ledger.save_episode_result
    commits = count_memory_commits(monkeypatch)

    def crash_after_child_result(request, result):
        save_result(request, result)
        raise FixtureCrash("child_result_persisted_before_verifier")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_child_result)
        with pytest.raises(FixtureCrash, match="child_result_persisted_before_verifier"):
            learner.run_brs(
                run_id=run_id, **PINS, practices=decisions, max_workers=2,
                budget={"deadline_unix": 101.0},
            )
    episode_ids = [f"{run_id}-practice-0-{i}" for i in range(2)]
    assert all(ledger.episode_result(episode_id) is not None for episode_id in episode_ids)
    assert verifier.calls == []
    reopened = RSILedger(ledger.database)

    result = resume(controller(reopened, gateway, verifier), reopened, run_id)

    assert result.status == "budget_exhausted"
    assert verifier.calls == [episode_ids[0]]
    assert len(gateway.requests) == 2
    assert commits == []
    assert reopened.get_episode(episode_ids[1]).payload["verifier"] is None
    assert reopened.episode_result(episode_ids[1])[1].status == "completed"
    assert reopened.get_run(run_id).state == "budget_exhausted"
    assert reopened.get_run(run_id).payload["budget_state"]["planned"]["deadline_unix"] == 101.0


def test_drs_verification_exhausting_deadline_stops_before_judgment(tmp_path, monkeypatch):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    clock = [100.0]
    verifier = DeadlineAdvancingVerifier(clock)
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: clock[0])
    result = controller(ledger, gateway, verifier).run_drs(
        run_id="deadline-before-judge", **PINS, budget={"deadline_unix": 101.0},
    )
    assert result.status == "budget_exhausted"
    assert len(gateway.requests) == len(verifier.calls) == 1
    assert ledger.controller_checkpoint(result.run_id)[1]["judgments"] == {}


def test_cancelled_unknown_without_raw_result_uses_intent_without_forging_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "cancelled-without-result"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    learner = controller(ledger, gateway)
    commits = count_memory_commits(monkeypatch)

    def lose_result(request, result):
        raise FixtureCrash("worker_result_not_saved")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", lose_result)
        with pytest.raises(FixtureCrash, match="worker_result_not_saved"):
            learner.run_drs(
                run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
                budget={"max_unknown_retries": 1},
            )
    episode_id = f"{run_id}-target-0"
    checkpoint = ledger.controller_checkpoint(run_id)
    request_before = checkpoint[1]["intents"][episode_id]["request"]
    head = ledger.get_episode(episode_id)
    unknown = ledger.reconcile_episode(
        episode_id, worker_state="unknown", expected_record_sha256=head.record_sha256,
        evidence={"reconciliation": {"source": "fixture_worker_disconnected"}},
    )
    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        resume(controller(RSILedger(ledger.database), gateway), ledger, run_id)
    cancelled = ledger.reconcile_episode(
        episode_id, worker_state="cancelled", expected_record_sha256=unknown.record_sha256,
        evidence={"reconciliation": {"source": "fixture_cancel_receipt", "cancel_confirmed": True}},
    )
    assert cancelled.state == "cancelled"
    assert ledger.episode_result(episode_id) is None
    reopened = RSILedger(ledger.database)

    result = resume(controller(reopened, gateway), reopened, run_id)

    assert result.status == "failed"
    assert result.target_attempts[0].episode.status == "cancelled"
    assert result.target_attempts[0].request.to_dict() == request_before
    assert reopened.episode_result(episode_id) is None
    assert reopened.get_episode(episode_id).state == "cancelled"
    assert reopened.get_run(run_id).state == "failed"
    assert len(gateway.requests) == 1
    assert commits == []
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT


def test_valid_hash_chain_cannot_roll_back_consumed_run_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    run_id = "budget-history-rollback"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway, verifier = RecordingGateway(), RecordingVerifier()
    save_result = ledger.save_episode_result

    def crash_after_result(request, result):
        save_result(request, result)
        raise FixtureCrash("result_before_checkpoint")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_after_result)
        with pytest.raises(FixtureCrash, match="result_before_checkpoint"):
            controller(ledger, gateway, verifier).run_drs(
                run_id=run_id, **PINS, max_practice_rounds=1, max_target_attempts=2,
                budget={"max_solver_invocations": 3},
            )
    head_before = ledger.get_run(run_id)
    previous_digest, state = ledger.controller_checkpoint(run_id)
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert head_before.payload["budget_state"]["consumed"]["solver_invocations"] == 0
    rolled_back = deepcopy(state)
    # Both consumed and derived remaining values are internally valid.  The forbidden change
    # is visible only by validating this new record against its earlier hash-chain history.
    rolled_back["budget_state"] = deepcopy(head_before.payload["budget_state"])
    with ledger.controller_lock(run_id):
        changed_digest = ledger.write_controller_checkpoint(
            run_id, rolled_back, expected_sha256=previous_digest,
        )
    assert ledger.controller_checkpoint_history(run_id)[-1] == (changed_digest, rolled_back)

    with pytest.raises(RSILearningError, match="rsi_resume_budget_drift"):
        resume(controller(RSILedger(ledger.database), gateway, verifier), ledger, run_id)

    assert len(gateway.requests) == 1
    assert verifier.calls == []
    assert ledger.get_run(run_id) == head_before
    assert ledger.controller_checkpoint(run_id) == (changed_digest, rolled_back)


@pytest.mark.parametrize("swapped_field", ["request", "verifier"])
def test_execution_recovery_rejects_cross_episode_component_swap(
    tmp_path: Path, swapped_field: str,
):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = RecordingGateway()
    result = controller(ledger, gateway).run_drs(
        run_id="execution-cross-binding", **PINS, max_practice_rounds=1, max_target_attempts=2,
    )
    assert result.status == "completed"
    first = RSILearningController._serialize_execution(result.target_attempts[0])
    second = RSILearningController._serialize_execution(result.target_attempts[1])
    assert RSILearningController._deserialize_execution(first) == result.target_attempts[0]
    assert RSILearningController._deserialize_execution(second) == result.target_attempts[1]
    crossed = deepcopy(first)
    crossed[swapped_field] = deepcopy(second[swapped_field])

    with pytest.raises(RSILearningError, match="rsi_resume_execution_conflict"):
        RSILearningController._deserialize_execution(crossed)

    assert len(gateway.requests) == 3
