"""Feature 160 stage 1 controller resume interruption matrix.

These fixtures model the crash windows around the gateway side effect.  They write the immutable
request/result envelope first, leave the canonical episode at ``running`` and then ask a fresh
controller instance to resume.  A valid resume must reconcile evidence in place and must never
invoke the gateway a second time.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    DeterministicCurriculum,
    RSILearningController,
    RSILearningError,
    RSILedger,
    RSIPracticeEpisode,
    SolverRequest,
    SolverResult,
    fixture_solver_gateway,
)

HEX = "a" * 64


class CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "counting"}

    def run(self, request: SolverRequest) -> SolverResult:
        self.calls += 1
        raise AssertionError("resume must not invoke the solver gateway")


class CompletedGateway:
    def __init__(self) -> None:
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "completed"}

    def run(self, request: SolverRequest) -> SolverResult:
        self.calls += 1
        return _result(request, "completed")


def _request(episode_id: str) -> SolverRequest:
    return SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="mock",
    )


def _result(request: SolverRequest, status: str) -> SolverResult:
    trace = hashlib.sha256(f"trace:{request.digest()}".encode()).hexdigest()
    completed = status == "completed"
    return SolverResult(
        episode_id=request.episode_id,
        request_sha256=request.digest(),
        status=status,
        candidate_receipt_sha256=HEX if completed else None,
        execution_receipt_sha256=HEX if completed else None,
        official_evaluation_receipt_sha256=HEX if completed else None,
        trace_digest=trace,
        solver_score=1.0 if completed else None,
        terminal_reason=f"fixture_{status}",
    )


def _interrupted_run(
    tmp_path: Path, *, episode_id: str, result: SolverResult | None,
) -> tuple[RSILedger, RSILearningController, CountingGateway, SolverRequest]:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = CountingGateway()
    controller = RSILearningController(gateway, ledger=ledger)
    run_record = controller._start_run(
        run_id="resume-matrix",
        mode="drs",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        budget={"max_target_attempts": 1, "max_practice_rounds": 0},
    )
    assert run_record is not None
    request = _request(episode_id)
    planned = RSIPracticeEpisode(
        episode_id=episode_id,
        run_id="resume-matrix",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="mock",
        status="planned",
        episode_kind="target",
    )
    running = planned.transition("running", request_sha256=request.digest())
    ledger.create_episode_record(running)
    if result is not None:
        ledger.save_episode_result(request, result)
    head = ledger.get("resume-matrix")
    assert head is not None
    ledger.transition(
        "resume-matrix",
        state="running",
        expected_record_sha256=head.record_sha256,
        payload_patch={"current_episode_id": episode_id},
    )
    return ledger, controller, gateway, request


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "abandoned", "cancelled"])
def test_resume_reconciles_persisted_result_without_gateway_call(
    tmp_path: Path, status: str,
) -> None:
    ledger, _controller, gateway, request = _interrupted_run(
        tmp_path, episode_id=f"target-{status}", result=_result(_request(f"target-{status}"), status)
    )
    fresh = RSILearningController(gateway, ledger=ledger)
    run = ledger.get("resume-matrix")
    assert run is not None

    resumed = fresh.resume(
        "resume-matrix",
        observed_fingerprints={"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]},
    )

    assert gateway.calls == 0
    episode = ledger.get_episode(request.episode_id)
    assert episode is not None
    assert episode.state == status
    journal = ledger.episode_reconciliation(request.episode_id)
    assert len(journal) == 1
    assert journal[0]["worker_state"] == status
    assert resumed.current_episode_id == request.episode_id

    # A second resume is a read-only replay of the same receipt and journal.
    resumed_again = fresh.resume(
        "resume-matrix",
        observed_fingerprints={"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]},
    )
    assert resumed_again.current_episode_id == request.episode_id
    assert len(ledger.episode_reconciliation(request.episode_id)) == 1


def test_resume_unknown_episode_without_result_remains_quarantined(tmp_path: Path) -> None:
    ledger, _controller, gateway, request = _interrupted_run(
        tmp_path, episode_id="target-unknown", result=None
    )
    episode = ledger.get_episode(request.episode_id)
    assert episode is not None
    unknown = RSIPracticeEpisode.from_dict(episode.payload).transition(
        "unknown", terminal_reason="fixture_lost_worker"
    )
    ledger.append_episode_record(unknown, expected_record_sha256=episode.record_sha256)
    fresh = RSILearningController(gateway, ledger=ledger)
    run = ledger.get("resume-matrix")
    assert run is not None

    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        fresh.resume(
            "resume-matrix",
            observed_fingerprints={"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]},
        )

    assert gateway.calls == 0
    assert ledger.get_episode(request.episode_id).state == "unknown"
    assert ledger.episode_reconciliation(request.episode_id) == ()


def test_resume_honors_controller_lock_and_does_not_mutate_checkpoint(tmp_path: Path) -> None:
    ledger, controller, gateway, _request_value = _interrupted_run(
        tmp_path, episode_id="target-lock", result=None
    )
    with ledger.controller_lock("resume-matrix"), pytest.raises(
        RSILearningError, match="rsi_controller_busy"
    ):
        controller.resume("resume-matrix")

    assert gateway.calls == 0
    assert len(ledger.controller_checkpoint_history("resume-matrix")) == 0


def test_resume_recovers_actual_result_publication_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = CompletedGateway()
    controller = RSILearningController(gateway, ledger=ledger)
    save_result = ledger.save_episode_result

    def stop_after_result(request: SolverRequest, result: SolverResult) -> None:
        save_result(request, result)
        raise RuntimeError("fixture_crash_after_result_publication")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", stop_after_result)
        with pytest.raises(RuntimeError, match="fixture_crash_after_result_publication"):
            controller.run_drs(
                run_id="resume-actual-crash", contract_sha256=HEX, evaluator_sha256=HEX,
                environment_sha256=HEX, solver_id="mock", max_practice_rounds=0,
                max_target_attempts=1,
            )
    episode_id = "resume-actual-crash-target-0"
    assert ledger.get_episode(episode_id).state == "running"
    assert ledger.episode_result(episode_id) is not None
    run = ledger.get_run("resume-actual-crash")
    assert run is not None

    recovered = RSILearningController(gateway, ledger=RSILedger(ledger.database)).resume(
        "resume-actual-crash",
        observed_fingerprints={"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]},
    )

    assert gateway.calls == 1
    assert ledger.episode_ids_for_run("resume-actual-crash") == (episode_id,)
    assert recovered.target_attempts[0].episode.episode_id == episode_id
    assert recovered.target_attempts[0].result == ledger.episode_result(episode_id)[1]


def test_concurrent_resume_has_one_writer_and_one_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode_id = "target-concurrent"
    ledger, controller, gateway, _request_value = _interrupted_run(
        tmp_path, episode_id=episode_id, result=_result(_request(episode_id), "completed")
    )
    run = ledger.get_run("resume-matrix")
    assert run is not None
    pins = {"run_fingerprint": run.payload["fingerprints"]["run_fingerprint"]}
    entered = threading.Event()
    release = threading.Event()
    get_episode = ledger.get_episode
    thread_errors: list[BaseException] = []

    def block_after_lock(requested_episode_id: str):
        entered.set()
        assert release.wait(timeout=5)
        return get_episode(requested_episode_id)

    def first_resume() -> None:
        try:
            controller.resume("resume-matrix", observed_fingerprints=pins)
        except RSILearningError as exc:
            thread_errors.append(exc)

    monkeypatch.setattr(ledger, "get_episode", block_after_lock)
    first = threading.Thread(target=first_resume)
    first.start()
    try:
        assert entered.wait(timeout=5)
        other = RSILearningController(gateway, ledger=RSILedger(ledger.database))
        with pytest.raises(RSILearningError, match="rsi_controller_busy"):
            other.resume("resume-matrix", observed_fingerprints=pins)
    finally:
        release.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert thread_errors == []
    assert gateway.calls == 0
    assert len(ledger.episode_reconciliation(episode_id)) == 1


def test_brs_resume_reconciles_child_result_after_controller_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BRS worker result is durable even when the owning controller dies before its wave save."""

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def rsi_fingerprint_config(self):
            return {"fixture": "brs-resume-v1"}

        def run(self, request: SolverRequest) -> SolverResult:
            self.calls.append(request.episode_id)
            return fixture_solver_gateway("mock").run(request)

    database = tmp_path / "rsi.sqlite3"
    gateway = Gateway()
    ledger = RSILedger(database)
    controller = RSILearningController(gateway, ledger=ledger)
    target = controller._target_episode(
        "brs-resume", "brs-resume-target", {
            "contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock",
        }, 0,
    )
    curriculum = DeterministicCurriculum()
    decisions = [
        curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i)
        for i in range(2)
    ]
    original_save = ledger.save_episode_result
    interrupted = False

    def save_then_interrupt(request: SolverRequest, result: SolverResult) -> None:
        nonlocal interrupted
        original_save(request, result)
        if request.episode_id.endswith("-0") and not interrupted:
            interrupted = True
            raise RuntimeError("fixture_controller_interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", save_then_interrupt)
        with pytest.raises(RuntimeError, match="fixture_controller_interrupted"):
            controller.run_brs(
                run_id="brs-resume", contract_sha256=HEX, evaluator_sha256=HEX,
                environment_sha256=HEX, solver_id="mock", practices=decisions,
            )

    assert interrupted
    assert gateway.calls == ["brs-resume-practice-0-0", "brs-resume-practice-0-1"]
    assert ledger.episode_result("brs-resume-practice-0-0") is not None
    assert ledger.episode_result("brs-resume-practice-0-1") is not None
    # The first child remains running because its immutable result was written before the crash.
    assert ledger.get_episode("brs-resume-practice-0-0").state == "running"

    resumed = RSILearningController(Gateway(), ledger=RSILedger(database)).resume("brs-resume")

    assert resumed.status == "completed"
    assert len(resumed.practice_episodes) == 2
    assert [item.episode.ordinal for item in resumed.practice_episodes] == [0, 1]
    # Recovery consumes the persisted result and does not dispatch either child again.
    assert gateway.calls == ["brs-resume-practice-0-0", "brs-resume-practice-0-1"]
    assert len(resumed.memory_snapshot.items) == 2


@pytest.mark.parametrize("terminal_status", ["cancelled", "timed_out", "abandoned"])
def test_brs_terminal_cancel_or_deadline_replays_without_dispatch(
    tmp_path: Path, terminal_status: str,
) -> None:
    """Cancellation/deadline terminals remain terminal across BRS restart."""

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def rsi_fingerprint_config(self):
            return {"fixture": "brs-terminal-replay-v1", "status": terminal_status}

        def run(self, request: SolverRequest) -> SolverResult:
            self.calls.append(request.episode_id)
            return fixture_solver_gateway("mock", terminal_status=terminal_status).run(request)

    database = tmp_path / "rsi.sqlite3"
    gateway = Gateway()
    ledger = RSILedger(database)
    controller = RSILearningController(gateway, ledger=ledger)
    target = controller._target_episode(
        f"brs-{terminal_status}", f"brs-{terminal_status}-target", {
            "contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock",
        }, 0,
    )
    decision = DeterministicCurriculum().choose(
        target=target, diagnosis="deadline-or-cancel", wave=0, ordinal=0,
    )
    result = controller.run_brs(
        run_id=f"brs-{terminal_status}", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX, solver_id="mock",
        practices=[decision],
    )

    assert result.status == "failed"
    assert result.practice_episodes[0].result.status == terminal_status
    assert gateway.calls == [f"brs-{terminal_status}-practice-0-0"]
    resumed = RSILearningController(Gateway(), ledger=RSILedger(database)).resume(
        f"brs-{terminal_status}"
    )
    assert resumed == result
    # A terminal cancellation/deadline is evidence, not permission for a retry.
    assert gateway.calls == [f"brs-{terminal_status}-practice-0-0"]
