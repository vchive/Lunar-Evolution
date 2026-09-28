"""Provider-free RSI learning control plane.

The controller sits above ``SolverGateway``.  It owns curriculum decisions, episode lineage and
memory promotion; a solver remains a replaceable candidate-search backend.  The implementation is
deliberately synchronous at the episode boundary so recovery can resume a durable episode without
silently launching a second request.  BRS uses a thread pool only for independent practice work,
then commits results in ordinal order against one frozen parent snapshot.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import (
    LocalExactVerifier,
    RSIMemoryStore,
    SolverGateway,
    SolverRequest,
    SolverResult,
)
from .rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    TransferReceipt,
    VerifierDecision,
)
from .rsi_store import RSILedger, RSIRecord


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value or len(value.encode("utf-8")) > 8192:
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


@dataclass(frozen=True)
class CurriculumDecision:
    """A bounded, auditable explanation for one practice selection."""

    practice_family: str
    capability_gap: str
    reason_code: str
    strategy: str
    expected_result: str
    failure_boundary: str
    compatible_solvers: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.practice_family, "practice_family"),
            (self.capability_gap, "capability_gap"),
            (self.reason_code, "reason_code"),
            (self.strategy, "strategy"),
            (self.expected_result, "expected_result"),
            (self.failure_boundary, "failure_boundary"),
        ):
            _bounded_text(value, name)
        if type(self.compatible_solvers) is not tuple or not self.compatible_solvers or len(self.compatible_solvers) > 32:
            raise RSILearningError("rsi_curriculum_solvers_invalid")
        for solver in self.compatible_solvers:
            _id(solver, "solver_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "practice_family": self.practice_family,
            "capability_gap": self.capability_gap,
            "reason_code": self.reason_code,
            "strategy": self.strategy,
            "expected_result": self.expected_result,
            "failure_boundary": self.failure_boundary,
            "compatible_solvers": list(self.compatible_solvers),
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())


class Curriculum(Protocol):
    def choose(
        self,
        *,
        target: PracticeEpisode,
        diagnosis: str,
        wave: int,
        ordinal: int,
    ) -> CurriculumDecision:
        """Choose one practice without executing a solver or mutating memory."""


class DeterministicCurriculum:
    """Small default curriculum suitable for local fixtures and recovery tests."""

    def __init__(
        self,
        *,
        practice_family: str = "target-gap-practice",
        strategy: str = "isolate the reported capability gap before retrying the target",
        expected_result: str = "the capability gap is covered by an independently verified receipt",
        failure_boundary: str = "does not generalize beyond the pinned contract and environment",
    ) -> None:
        self._template = (practice_family, strategy, expected_result, failure_boundary)

    def choose(self, *, target: PracticeEpisode, diagnosis: str, wave: int, ordinal: int) -> CurriculumDecision:
        del wave, ordinal
        family, strategy, expected, boundary = self._template
        return CurriculumDecision(
            practice_family=family,
            capability_gap=diagnosis or "target capability gap",
            reason_code="target_failure_gap" if target.episode_kind == "target" else "practice_followup",
            strategy=strategy,
            expected_result=expected,
            failure_boundary=boundary,
            compatible_solvers=(target.solver_id,),
        )


@dataclass(frozen=True)
class EpisodeExecution:
    episode: PracticeEpisode
    request: SolverRequest
    result: SolverResult
    verifier: VerifierDecision

    @property
    def passed(self) -> bool:
        return (
            self.episode.status == self.result.status == "completed"
            and self.episode.verifier == self.verifier
            and self.verifier.outcome == "pass"
        )


class PracticeEpisodeRunner:
    """Execute one planned episode and attach an independent verifier decision."""

    def __init__(
        self,
        gateway: SolverGateway,
        verifier: Any | None = None,
        ledger: RSILedger | None = None,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier or LocalExactVerifier()
        self.ledger = ledger

    def _create_running_record(self, episode: PracticeEpisode) -> RSIRecord | None:
        if self.ledger is None:
            return None
        return self.ledger.create_episode_record(episode)

    def _append_record(self, episode: PracticeEpisode, parent: RSIRecord | None) -> RSIRecord | None:
        if self.ledger is None:
            return None
        if parent is None:
            raise RSILearningError("rsi_episode_ledger_parent_missing")
        return self.ledger.append_episode_record(
            episode,
            expected_record_sha256=parent.record_sha256,
        )

    def run(self, episode: PracticeEpisode, request: SolverRequest) -> EpisodeExecution:
        if episode.status != "planned":
            raise RSILearningError("rsi_episode_runner_requires_planned")
        if (
            request.episode_id != episode.episode_id
            or request.solver_id != episode.solver_id
            or request.contract_sha256 != episode.contract_sha256
            or request.evaluator_sha256 != episode.evaluator_sha256
        ):
            raise RSILearningError("rsi_episode_request_mismatch")
        if request.environment_sha256 != episode.environment_sha256 or request.memory_snapshot_sha256 != episode.memory_snapshot_sha256:
            raise RSILearningError("rsi_episode_request_mismatch")
        running = episode.transition("running", request_sha256=request.digest())
        ledger_head = self._create_running_record(running)
        result = self.gateway.run(request)
        if result.request_sha256 != request.digest() or result.episode_id != episode.episode_id:
            raise RSILearningError("rsi_solver_result_identity_mismatch")
        if result.status == "completed":
            finished = running.transition(
                "completed",
                candidate_receipt_sha256=result.candidate_receipt_sha256,
                execution_receipt_sha256=result.execution_receipt_sha256,
                official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
                trace_digest=result.trace_digest,
                candidate_source_sha256=result.candidate_source_sha256,
                dependency_sha256=result.dependency_sha256,
                trace_events=result.trace_events,
                actor_fingerprint=result.actor_fingerprint,
                solver_fingerprint=_record_digest({"solver_id": request.solver_id, "settings": request.solver_settings}),
            )
        else:
            finished = running.transition(
                "unknown" if result.status == "unknown" else result.status,
                trace_digest=result.trace_digest,
                trace_events=result.trace_events,
                candidate_source_sha256=result.candidate_source_sha256,
                dependency_sha256=result.dependency_sha256,
                solver_fingerprint=_record_digest({"solver_id": request.solver_id, "settings": request.solver_settings}),
                actor_fingerprint=result.actor_fingerprint,
                terminal_reason=result.terminal_reason or f"solver_{result.status}",
            )
        ledger_head = self._append_record(finished, ledger_head)
        decision = self.verifier.verify(finished, request, result)
        if finished.status != "completed":
            # A terminal worker cannot carry a verifier decision in the episode record. The decision
            # remains returned as diagnostic evidence and is never eligible for memory promotion.
            return EpisodeExecution(finished, request, result, decision)
        verified = finished.attach_verifier(decision)
        self._append_record(verified, ledger_head)
        return EpisodeExecution(verified, request, result, decision)


TargetJudge = Callable[[EpisodeExecution], tuple[bool, str]]


def default_target_judge(execution: EpisodeExecution) -> tuple[bool, str]:
    if not execution.passed:
        return False, execution.verifier.diagnosis
    score = execution.result.solver_score
    if score is not None and score < 1.0:
        return False, "target exact evaluator did not meet the acceptance threshold"
    return True, "target accepted by exact evaluator"


@dataclass(frozen=True)
class LearningRunResult:
    run_id: str
    status: str
    memory_snapshot: MemorySnapshot
    target_attempts: tuple[EpisodeExecution, ...]
    practice_episodes: tuple[EpisodeExecution, ...]
    transfer: TransferReceipt | None = None


class FrozenMemoryTransferRunner:
    """Run a target with a read-only snapshot and no curriculum or memory writes."""

    def __init__(
        self,
        gateway: SolverGateway,
        verifier: Any | None = None,
        target_judge: TargetJudge = default_target_judge,
        ledger: RSILedger | None = None,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier or LocalExactVerifier()
        self.target_judge = target_judge
        self.ledger = ledger

    def reject_memory_write(self) -> None:
        raise RSILearningError("rsi_transfer_memory_write_disabled")

    def run(
        self,
        *,
        run_id: str,
        target_id: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        snapshot: MemorySnapshot,
        budget: Mapping[str, Any] | None = None,
    ) -> tuple[TransferReceipt, EpisodeExecution]:
        _id(run_id, "run_id")
        _id(target_id, "target_id")
        request = SolverRequest.build(
            episode_id=target_id,
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            memory_snapshot_sha256=snapshot.digest(),
            solver_id=solver_id,
            budget=budget,
            practice_charter={"curriculum_enabled": False, "memory_write_enabled": False},
        )
        episode = PracticeEpisode(
            target_id, run_id, contract_sha256, evaluator_sha256, environment_sha256,
            snapshot.digest(), solver_id, "planned", episode_kind="target",
        )
        execution = PracticeEpisodeRunner(self.gateway, self.verifier, self.ledger).run(episode, request)
        accepted, _diagnosis = self.target_judge(execution)
        status = "passed" if accepted and execution.passed else (
            "unknown" if execution.result.status == "unknown" else "failed"
        )
        receipt = TransferReceipt(
            run_id=run_id,
            target_id=target_id,
            memory_snapshot_sha256=snapshot.digest(),
            evaluator_sha256=evaluator_sha256,
            solver_fingerprint=request.digest(),
            status=status,
            official_evaluation_receipt_sha256=execution.result.official_evaluation_receipt_sha256 or _record_digest({"status": status, "target": target_id}),
        )
        if self.ledger is not None:
            self.ledger.create_transfer_receipt(receipt)
        return receipt, execution


class RSILearningController:
    """DRS/BRS orchestration above the solver gateway."""

    def __init__(
        self,
        gateway: SolverGateway,
        *,
        verifier: Any | None = None,
        curriculum: Curriculum | None = None,
        memory_store: RSIMemoryStore | None = None,
        target_judge: TargetJudge = default_target_judge,
        ledger: RSILedger | None = None,
        solver_settings: Mapping[str, Any] | None = None,
        actor_fingerprint: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier or LocalExactVerifier()
        self.curriculum = curriculum or DeterministicCurriculum()
        self.memory_store = memory_store or RSIMemoryStore(EMPTY_MEMORY_SNAPSHOT)
        self.target_judge = target_judge
        self.ledger = ledger
        self._explicit_memory_store = memory_store is not None
        self.solver_settings = dict(solver_settings or {})
        if actor_fingerprint is not None:
            _digest(actor_fingerprint, "actor_fingerprint")
        self.actor_fingerprint = actor_fingerprint

    def resume(
        self, *, run_id: str, contract_sha256: str | None = None,
        evaluator_sha256: str | None = None, environment_sha256: str | None = None,
        solver_id: str | None = None, solver_settings: Mapping[str, Any] | None = None,
        actor_fingerprint: str | None = None,
    ) -> LearningRunResult:
        """Resume durable work; unresolved launches require explicit evidence reconciliation."""
        from .rsi_recovery import DurableLearningRun
        return DurableLearningRun(self, run_id).resume({
            "contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256,
            "environment_sha256": environment_sha256, "solver_id": solver_id,
            "solver_settings": dict(solver_settings) if solver_settings is not None else None,
            "actor_fingerprint": actor_fingerprint,
        })

    def reconcile_episode(
        self, *, run_id: str, episode_id: str, result: SolverResult,
        expected_record_sha256: str,
    ) -> LearningRunResult:
        """Settle an original uncertain request with terminal evidence, then continue its run."""
        from .rsi_recovery import DurableLearningRun
        return DurableLearningRun(self, run_id).reconcile(episode_id, result, expected_record_sha256)

    @property
    def snapshot(self) -> MemorySnapshot:
        return self.memory_store.snapshot

    def _start_run(
        self,
        *,
        run_id: str,
        mode: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        budget: Mapping[str, Any] | None,
    ) -> RSIRecord | None:
        if self.ledger is None:
            return None
        payload = {
            "mode": mode,
            "contract_sha256": contract_sha256,
            "evaluator_sha256": evaluator_sha256,
            "environment_sha256": environment_sha256,
            "solver_id": solver_id,
            "budget": dict(budget or {}),
        }
        request_sha256 = _record_digest({"run_id": run_id, **payload})
        created = self.ledger.create_run(run_id, request_sha256, payload)
        return self.ledger.transition(run_id, state="running", expected_record_sha256=created.record_sha256)

    def _finish_run(self, record: RSIRecord | None, result: LearningRunResult) -> None:
        if self.ledger is None or record is None:
            return
        self.ledger.transition(
            result.run_id,
            state=result.status,
            expected_record_sha256=record.record_sha256,
            payload_patch={
                "target_attempts": len(result.target_attempts),
                "practice_episodes": len(result.practice_episodes),
                "memory_snapshot_sha256": result.memory_snapshot.digest(),
                "transfer_status": result.transfer.status if result.transfer is not None else None,
            },
        )

    def _target_episode(self, run_id: str, target_id: str, pins: Mapping[str, str], attempt: int) -> PracticeEpisode:
        return PracticeEpisode(
            target_id, run_id, pins["contract_sha256"], pins["evaluator_sha256"], pins["environment_sha256"],
            self.snapshot.digest(), pins["solver_id"], "planned", episode_kind="target", wave=attempt, ordinal=0,
        )

    def _request(self, episode: PracticeEpisode, *, budget: Mapping[str, Any] | None = None, charter: Mapping[str, Any] | None = None) -> SolverRequest:
        return SolverRequest.build(
            episode_id=episode.episode_id, contract_sha256=episode.contract_sha256,
            evaluator_sha256=episode.evaluator_sha256, environment_sha256=episode.environment_sha256,
            memory_snapshot_sha256=episode.memory_snapshot_sha256, solver_id=episode.solver_id,
            budget=budget, practice_charter=charter,
        )

    def _practice(self, *, run_id: str, target: PracticeEpisode, decision: CurriculumDecision, wave: int, ordinal: int) -> EpisodeExecution:
        episode = PracticeEpisode(
            f"{run_id}-practice-{wave}-{ordinal}", run_id, target.contract_sha256, target.evaluator_sha256,
            target.environment_sha256, self.snapshot.digest(), target.solver_id, "planned",
            episode_kind="practice", wave=wave, ordinal=ordinal, parent_target_episode_id=target.episode_id,
        )
        request = self._request(episode, charter={**decision.to_dict(), "decision_sha256": decision.digest()})
        return PracticeEpisodeRunner(self.gateway, self.verifier, self.ledger).run(episode, request)

    def _commit(
        self,
        execution: EpisodeExecution,
        decision: CurriculumDecision,
        *,
        expected_episode_snapshot_sha256: str | None = None,
        source_snapshot_sha256: str | None = None,
    ) -> MemorySnapshot:
        if not execution.passed:
            return self.snapshot
        memory = MemoryItem(
            memory_id=f"memory-{execution.episode.episode_id}",
            problem_family=decision.practice_family,
            trigger=decision.capability_gap,
            strategy=decision.strategy,
            expected_result=decision.expected_result,
            failure_boundary=decision.failure_boundary,
            condition=decision.capability_gap,
            action=decision.strategy,
            observed_result=decision.expected_result,
            applicability=decision.failure_boundary,
            compatible_contracts=(execution.episode.contract_sha256,),
            compatible_solvers=decision.compatible_solvers,
            verifier_outcome="pass",
            receipt_sha256=execution.verifier.receipt_sha256,
            episode_id=execution.episode.episode_id,
        )
        snapshot = self.memory_store.commit(
            parent_snapshot_sha256=self.snapshot.digest(),
            episode=execution.episode,
            decision=execution.verifier,
            memory=memory,
            expected_episode_snapshot_sha256=expected_episode_snapshot_sha256,
            source_snapshot_sha256=source_snapshot_sha256,
        )
        if self.ledger is not None:
            self.ledger.create_memory_snapshot(snapshot)
        return snapshot

    def run_drs(
        self,
        *,
        run_id: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        max_practice_rounds: int = 3,
        max_target_attempts: int = 4,
        budget: Mapping[str, Any] | None = None,
    ) -> LearningRunResult:
        _id(run_id, "run_id")
        for value, name in ((contract_sha256, "contract_sha256"), (evaluator_sha256, "evaluator_sha256"), (environment_sha256, "environment_sha256")):
            _digest(value, name)
        if (type(max_practice_rounds) is not int or type(max_target_attempts) is not int
                or max_practice_rounds < 0 or max_target_attempts < 1):
            raise RSILearningError("rsi_learning_budget_invalid")
        if self.ledger is not None:
            from .rsi_recovery import DurableLearningRun
            return DurableLearningRun(self, run_id).start("drs", {
                "contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256, "solver_id": solver_id,
                "budget": dict(budget or {}), "max_practice_rounds": max_practice_rounds,
                "max_target_attempts": max_target_attempts,
            })
        pins = {"contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256, "environment_sha256": environment_sha256, "solver_id": solver_id}
        run_record = self._start_run(
            run_id=run_id, mode="drs", contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256, environment_sha256=environment_sha256,
            solver_id=solver_id, budget=budget,
        )
        targets: list[EpisodeExecution] = []
        practices: list[EpisodeExecution] = []
        for attempt in range(max_target_attempts):
            target = self._target_episode(run_id, f"{run_id}-target-{attempt}", pins, attempt)
            request = self._request(target, budget=budget)
            execution = PracticeEpisodeRunner(self.gateway, self.verifier, self.ledger).run(target, request)
            targets.append(execution)
            accepted, diagnosis = self.target_judge(execution)
            if accepted and execution.passed:
                result = LearningRunResult(run_id, "completed", self.snapshot, tuple(targets), tuple(practices))
                self._finish_run(run_record, result)
                return result
            # A worker whose terminal evidence is uncertain cannot be followed by an automatic
            # practice or retry.  Recovery must reconcile that episode first; otherwise a later
            # successful fixture could be incorrectly promoted as learning from an unknown run.
            if execution.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}:
                status = "unknown" if execution.result.status == "unknown" else "failed"
                result = LearningRunResult(run_id, status, self.snapshot, tuple(targets), tuple(practices))
                self._finish_run(run_record, result)
                return result
            if attempt >= max_practice_rounds:
                break
            decision = self.curriculum.choose(target=execution.episode, diagnosis=diagnosis, wave=attempt, ordinal=0)
            practice = self._practice(run_id=run_id, target=execution.episode, decision=decision, wave=attempt, ordinal=0)
            practices.append(practice)
            # A practice worker with uncertain or terminal-but-unverified evidence cannot feed a
            # retry.  Reconciliation must settle the worker before the controller launches more
            # work; in particular, ``unknown`` must never become an implicit successful lesson.
            if practice.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}:
                status = "unknown" if practice.result.status == "unknown" else "failed"
                result = LearningRunResult(run_id, status, self.snapshot, tuple(targets), tuple(practices))
                self._finish_run(run_record, result)
                return result
            self._commit(practice, decision)
        status = "unknown" if targets and targets[-1].result.status == "unknown" else "failed"
        result = LearningRunResult(run_id, status, self.snapshot, tuple(targets), tuple(practices))
        self._finish_run(run_record, result)
        return result

    def run_brs(
        self,
        *,
        run_id: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        practices: Sequence[CurriculumDecision],
        wave: int = 0,
        budget: Mapping[str, Any] | None = None,
        max_workers: int | None = None,
    ) -> LearningRunResult:
        _id(run_id, "run_id")
        for value, name in ((contract_sha256, "contract_sha256"), (evaluator_sha256, "evaluator_sha256"), (environment_sha256, "environment_sha256")):
            _digest(value, name)
        _id(solver_id, "solver_id")
        if type(wave) is not int or wave < 0 or (max_workers is not None and (type(max_workers) is not int or max_workers < 1)):
            raise RSILearningError("rsi_learning_budget_invalid")
        if self.ledger is not None:
            from .rsi_recovery import DurableLearningRun
            return DurableLearningRun(self, run_id).start("brs", {
                "contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256, "solver_id": solver_id,
                "budget": dict(budget or {}), "practices": [decision.to_dict() for decision in practices],
                "wave": wave, "max_workers": max_workers,
            })
        run_record = self._start_run(
            run_id=run_id, mode="brs", contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256, environment_sha256=environment_sha256,
            solver_id=solver_id, budget=budget,
        )
        target = self._target_episode(run_id, f"{run_id}-target-seed", {"contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256, "environment_sha256": environment_sha256, "solver_id": solver_id}, wave)
        if not practices:
            result = LearningRunResult(run_id, "completed", self.snapshot, (), ())
            self._finish_run(run_record, result)
            return result
        frozen_parent = self.snapshot.digest()
        def launch(pair: tuple[int, CurriculumDecision]) -> EpisodeExecution:
            ordinal, decision = pair
            if self.snapshot.digest() != frozen_parent:
                raise RSILearningError("rsi_brs_snapshot_changed")
            return self._practice(run_id=run_id, target=target, decision=decision, wave=wave, ordinal=ordinal)
        with ThreadPoolExecutor(max_workers=max_workers or len(practices)) as pool:
            results = list(pool.map(launch, enumerate(practices)))
        uncertain = [
            execution.result.status
            for execution in results
            if execution.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}
        ]
        if uncertain:
            status = "unknown" if "unknown" in uncertain else "failed"
            result = LearningRunResult(run_id, status, self.snapshot, (), tuple(results))
            self._finish_run(run_record, result)
            return result
        committed: list[EpisodeExecution] = []
        for execution, decision in zip(results, practices):
            # Every BRS child was launched from the same frozen parent.  The store's CAS check
            # protects the ordered commits, while this check protects provenance: a child that
            # accidentally observed a newer snapshot is never merged into this wave.
            if execution.episode.memory_snapshot_sha256 != frozen_parent:
                raise RSILearningError("rsi_brs_snapshot_changed")
            if execution.passed:
                self._commit(
                    execution,
                    decision,
                    expected_episode_snapshot_sha256=frozen_parent,
                    source_snapshot_sha256=frozen_parent,
                )
                committed.append(execution)
        result = LearningRunResult(run_id, "completed", self.snapshot, (), tuple(results))
        self._finish_run(run_record, result)
        return result


__all__ = [
    "Curriculum",
    "CurriculumDecision",
    "DeterministicCurriculum",
    "EpisodeExecution",
    "FrozenMemoryTransferRunner",
    "LearningRunResult",
    "PracticeEpisodeRunner",
    "RSILearningController",
    "TargetJudge",
    "default_target_judge",
]
