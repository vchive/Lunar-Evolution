"""Provider-free RSI learning control plane.

The controller sits above ``SolverGateway``.  It owns curriculum decisions, episode lineage and
memory promotion; a solver remains a replaceable candidate-search backend.  The implementation is
deliberately synchronous at the episode boundary so recovery can resume a durable episode without
silently launching a second request.  BRS uses a thread pool only for independent practice work,
then commits results in ordinal order against one frozen parent snapshot.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_callbacks import DurableCallbackJournal
from .rsi_fingerprint import RSIFingerprintContract, ensure_fingerprint_compatible
from .rsi_gateway import (
    LocalExactVerifier,
    RSIMemoryStore,
    SolverGateway,
    SolverRequest,
    SolverResult,
)
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    MemoryItem,
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    TransferReceipt,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_store import RSILedger, RSIRecord
from .rsi_usage import RSIUsageError, UsageReceipt
from .rsi_usage import UsageLedger as RSIUsageLedger


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


def _component_digest(value: object, *, name: str) -> str:
    """Return a stable local component identity; mutable instances must opt in explicitly."""

    try:
        return component_fingerprint(value)
    except RSIIdentityError as exc:
        raise RSILearningError(f"rsi_{name}_fingerprint_invalid") from exc


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

    def rsi_fingerprint_config(self) -> dict[str, str]:
        """Expose only the immutable curriculum template to the run identity contract."""

        family, strategy, expected, boundary = self._template
        return {
            "practice_family": family,
            "strategy": strategy,
            "expected_result": expected,
            "failure_boundary": boundary,
        }

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
        return self.verifier.outcome == "pass"


class PracticeEpisodeRunner:
    """Execute one planned episode and attach an independent verifier decision."""

    def __init__(
        self,
        gateway: SolverGateway,
        verifier: Any | None = None,
        ledger: RSILedger | None = None,
        usage_ledger: RSIUsageLedger | None = None,
        *, before_verify: Callable[[], None] | None = None,
        before_run: Callable[[], None] | None = None,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier or LocalExactVerifier()
        self.ledger = ledger
        self.usage_ledger = usage_ledger
        self.before_verify = before_verify
        self.before_run = before_run

    @staticmethod
    def _usage_event_id(episode: PracticeEpisode, request: SolverRequest) -> str:
        """Derive one stable sidecar event identity for the physical solver invocation."""

        return "rsi-solver-" + _record_digest({
            "run_id": episode.run_id,
            "episode_id": episode.episode_id,
            "request_sha256": request.digest(),
        })

    def _record_solver_usage(self, episode: PracticeEpisode, request: SolverRequest,
                             started_ns: int, finished_ns: int) -> None:
        if self.usage_ledger is None:
            return
        elapsed_ns = max(0, finished_ns - started_ns)
        # This is local monotonic elapsed time, not provider billing truth.  The append is
        # intentionally idempotent by event_id; append() (rather than record()) obtains the
        # current head under its file lock, which also makes concurrent BRS workers safe.
        self.usage_ledger.append(UsageReceipt(
            event_id=self._usage_event_id(episode, request),
            run_id=episode.run_id,
            episode_id=episode.episode_id,
            adapter_stage="solver",
            wall_time_ms=elapsed_ns // 1_000_000,
            input_tokens=None,
            output_tokens=None,
            cpu_time_ms=None,
        ))

    @classmethod
    def ensure_unknown_solver_usage(
        cls, usage_ledger: RSIUsageLedger | None, episode: PracticeEpisode,
        request: SolverRequest,
    ) -> None:
        """Record a replay gap without inventing elapsed time.

        A durable solver result proves that a side effect happened, but it carries no trustworthy
        local duration.  The unknown receipt keeps that gap visible while preserving the same
        event identity used by a normal invocation.
        """

        if usage_ledger is None:
            return
        event_id = cls._usage_event_id(episode, request)
        if any(item.event_id == event_id for item in usage_ledger.records()):
            return
        try:
            usage_ledger.append(UsageReceipt(
                event_id=event_id,
                run_id=episode.run_id,
                episode_id=episode.episode_id,
                adapter_stage="solver",
                wall_time_ms=None,
                input_tokens=None,
                output_tokens=None,
                cpu_time_ms=None,
            ))
        except RSIUsageError as exc:
            # Another controller may have appended the same replay marker after our read.  The
            # append-only ledger remains authoritative; accept only that exact event race.
            if str(exc) != "rsi_usage_event_conflict" or not any(
                item.event_id == event_id for item in usage_ledger.records()
            ):
                raise

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
        if self.before_run is not None:
            self.before_run()
        running = episode.transition("running", request_sha256=request.digest())
        ledger_head = self._create_running_record(running)
        started_ns = time.monotonic_ns()
        try:
            result = self.gateway.run(request)
        except Exception as gateway_error:
            # Preserve the gateway exception if accounting itself cannot be appended.  A missing
            # sidecar record is explicit incomplete evidence; it must not be mistaken for a
            # zero-cost or exactly-once provider observation.
            try:
                self._record_solver_usage(episode, request, started_ns, time.monotonic_ns())
            except Exception as accounting_error:
                raise gateway_error from accounting_error
            raise
        self._record_solver_usage(episode, request, started_ns, time.monotonic_ns())
        if self.ledger is not None:
            # Persist the immutable worker result before advancing the episode head.  If the
            # controller dies after the gateway side effect, reconcile can inspect this exact
            # request/result pair without invoking the solver again.
            self.ledger.save_episode_result(request, result)
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
        if self.before_verify is not None:
            self.before_verify()
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
    checkpoint_episode_id: str | None = None

    @property
    def current_episode_id(self) -> str | None:
        if self.checkpoint_episode_id is not None:
            return self.checkpoint_episode_id
        if self.target_attempts:
            return self.target_attempts[-1].episode.episode_id
        if self.practice_episodes:
            return self.practice_episodes[-1].episode.episode_id
        return None


class FrozenMemoryTransferRunner:
    """Run one frozen-memory transfer with durable, namespaced recovery evidence."""

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

    @staticmethod
    def _identity(run_id: str, target_id: str) -> str:
        return "rsi-transfer-" + _record_digest({"run_id": run_id, "target_id": target_id})

    @staticmethod
    def _receipt(value: Mapping[str, Any]) -> TransferReceipt:
        receipt = TransferReceipt(**{key: value[key] for key in (
            "run_id", "target_id", "memory_snapshot_sha256", "evaluator_sha256",
            "solver_fingerprint", "status", "official_evaluation_receipt_sha256",
        )})
        if receipt.to_dict() != {key: item for key, item in value.items() if key != "reconciliation"}:
            raise RSILearningError("rsi_transfer_checkpoint_corrupt")
        return receipt

    @staticmethod
    def _verdict(value: Mapping[str, Any]) -> VerifierDecision:
        clean = dict(value)
        clean["checks"] = tuple(VerifierCheck(**item) for item in clean["checks"])
        return VerifierDecision(**clean)

    def _make_receipt(self, run_id: str, target_id: str, snapshot: MemorySnapshot,
                      execution: EpisodeExecution, accepted: bool) -> TransferReceipt:
        status = ("unknown" if execution.result.status == "unknown" else
                  "passed" if accepted and execution.passed and execution.result.status == "completed" else "failed")
        return TransferReceipt(
            run_id=run_id, target_id=target_id, memory_snapshot_sha256=snapshot.digest(),
            evaluator_sha256=execution.request.evaluator_sha256,
            solver_fingerprint=execution.request.digest(), status=status,
            official_evaluation_receipt_sha256=(execution.result.official_evaluation_receipt_sha256
                                               or _record_digest({"status": status, "target": target_id})),
        )

    @staticmethod
    def _validate_execution(execution: EpisodeExecution, request: SolverRequest, internal_id: str) -> None:
        episode = execution.episode
        if (
            execution.request.to_dict() != request.to_dict()
            or episode.run_id != internal_id
            or episode.episode_id != request.episode_id
            or episode.request_sha256 != request.digest()
            or episode.solver_id != request.solver_id
            or episode.contract_sha256 != request.contract_sha256
            or episode.evaluator_sha256 != request.evaluator_sha256
            or episode.environment_sha256 != request.environment_sha256
            or episode.memory_snapshot_sha256 != request.memory_snapshot_sha256
            or execution.result.episode_id != request.episode_id
            or execution.result.request_sha256 != request.digest()
            or episode.status != execution.result.status
            or execution.verifier.episode_id != episode.episode_id
            or (episode.status == "completed" and episode.verifier != execution.verifier)
        ):
            raise RSILearningError("rsi_transfer_checkpoint_corrupt")

    def _components(self) -> dict[str, str]:
        return {
            "gateway": _component_digest(self.gateway, name="solver"),
            "verifier": _component_digest(self.verifier, name="verifier"),
            "judge": _component_digest(self.target_judge, name="target_judge"),
        }

    def _reconcile_state(self, run_id: str, target_id: str) -> tuple[str, dict[str, Any], SolverRequest]:
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        previous = self.ledger.controller_checkpoint(self._identity(run_id, target_id))
        if previous is None:
            raise RSILearningError("rsi_transfer_recovery_required")
        digest, state = previous
        intent = state.get("intent", {})
        if (state.get("kind") != "rsi_transfer_checkpoint" or state.get("schema_version") != "1"
                or intent.get("run_id") != run_id or intent.get("target_id") != target_id):
            raise RSILearningError("rsi_transfer_checkpoint_corrupt")
        if intent.get("components") != self._components():
            raise RSILearningError("rsi_transfer_fingerprint_drift")
        request = SolverRequest.from_dict(intent["request"])
        snapshot = MemorySnapshot.from_dict(intent["snapshot"])
        if (request.episode_id != self._identity(run_id, target_id) + "-target"
                or request.memory_snapshot_sha256 != snapshot.digest()
                or dict(request.budget) != state["budget_policy"]):
            raise RSILearningError("rsi_transfer_checkpoint_corrupt")
        current_budget = RSIRunBudget.load(state["budget_state"])
        current_budget.assert_matches(state["budget_policy"])
        consumed: dict[str, int] = {}
        for _old_digest, old in self.ledger.controller_checkpoint_history(self._identity(run_id, target_id)):
            old_budget = RSIRunBudget.load(old["budget_state"])
            counters = old_budget.to_dict()["consumed"]
            if (old.get("intent") != intent or old.get("budget_policy") != state["budget_policy"]
                    or old_budget.to_dict()["planned"] != current_budget.to_dict()["planned"]
                    or any(used > counters[key] for key, used in consumed.items())):
                raise RSILearningError("rsi_resume_budget_drift")
            consumed = counters
        return digest, state, request

    @staticmethod
    def _callback_evidence(intent: Mapping[str, Any], result: Mapping[str, Any], stage: str,
                           evidence: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "source", "binding_sha256", "result_sha256", "receipt_sha256",
        }:
            raise RSILearningError("rsi_transfer_reconcile_evidence_invalid")
        _bounded_text(evidence["source"], "reconcile_source")
        receipt = result.get("receipt_sha256") if stage == "verifier" else _record_digest(result)
        if (evidence["binding_sha256"] != _record_digest(intent)
                or evidence["result_sha256"] != _record_digest(result)
                or evidence["receipt_sha256"] != receipt):
            raise RSILearningError("rsi_transfer_reconcile_evidence_invalid")
        return dict(evidence)

    @staticmethod
    def _validate_verifier_result(value: Mapping[str, Any], episode: PracticeEpisode,
                                  request: SolverRequest, result: SolverResult) -> VerifierDecision:
        try:
            decision = FrozenMemoryTransferRunner._verdict(value)
        except (TypeError, KeyError, ValueError) as exc:
            raise RSILearningError("rsi_transfer_verifier_result_invalid") from exc
        receipts = ("candidate_receipt_sha256", "execution_receipt_sha256",
                    "official_evaluation_receipt_sha256")
        expected_evidence = _record_digest({
            **{key: getattr(result, key) for key in receipts}, "trace_digest": result.trace_digest,
        })
        if (decision.to_dict() != value or decision.episode_id != episode.episode_id
                or any(getattr(decision, key) != getattr(request, key) for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256"))
                or any(getattr(decision, key) != getattr(result, key) for key in receipts)
                or decision.evidence_sha256 != expected_evidence
                or (decision.outcome == "pass" and (
                    result.status != "completed" or not decision.independent_of_actor
                    or any(getattr(result, key) is None for key in receipts)
                    or any(check.outcome != "pass" for check in decision.checks)))):
            raise RSILearningError("rsi_transfer_verifier_result_invalid")
        return decision

    def reconcile_callback(
        self, run_id: str, target_id: str, *, stage: str, expected_checkpoint_sha256: str,
        result: Mapping[str, Any], evidence: Mapping[str, Any],
    ) -> str:
        """Record an externally observed callback result without invoking any callback.

        Evidence binds the complete frozen transfer intent, the canonical callback result and
        its receipt (a verifier receipt, or the judgment's canonical digest). This is trusted
        local evidence admission, not an attestation of a remote verifier's authenticity.
        """
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        if stage not in {"verifier", "judge"} or not isinstance(result, Mapping):
            raise RSILearningError("rsi_transfer_callback_stage_invalid")
        _digest(expected_checkpoint_sha256, "expected_checkpoint_sha256")
        internal_id = self._identity(run_id, target_id)
        with self.ledger.controller_lock(internal_id):
            current, state, request = self._reconcile_state(run_id, target_id)
            field = "verifier" if stage == "verifier" else "judgment"
            clean_result = dict(result)
            clean_evidence = self._callback_evidence(state["intent"], clean_result, stage, evidence)
            reconciliation = {
                "stage": stage, "parent_checkpoint_sha256": expected_checkpoint_sha256,
                "result": clean_result, "evidence": clean_evidence,
            }
            previous = state.get("callback_reconciliations", {}).get(stage)
            if previous is not None:
                # Exact old-CAS replay is allowed after later phases; differing evidence is not.
                if all(previous.get(key) == value for key, value in reconciliation.items()):
                    saved = self.ledger.episode_result(request.episode_id)
                    records = self.ledger.history(request.episode_id)
                    if (saved is None or saved[0] != request
                            or _record_digest(saved[1].to_dict()) != previous.get("solver_result_sha256")
                            or previous.get("episode_record_sha256") not in {
                                item.record_sha256 for item in records}):
                        raise RSILearningError("rsi_transfer_checkpoint_corrupt")
                    return current
                raise RSILearningError("rsi_transfer_reconcile_conflict")
            if current != expected_checkpoint_sha256:
                raise RSILearningError("rsi_controller_checkpoint_conflict")
            if not state.get(stage + "_started") or state.get(field) is not None:
                raise RSILearningError("rsi_transfer_callback_reconcile_not_required")
            head = self.ledger.get_episode(request.episode_id)
            persisted = self.ledger.episode_result(request.episode_id)
            if head is None or persisted is None:
                raise RSILearningError("rsi_transfer_recovery_required")
            saved_request, saved_result = persisted
            episode = PracticeEpisode.from_dict(head.payload)
            if (saved_request != request or episode.status != saved_result.status
                    or episode.run_id != internal_id or episode.request_sha256 != request.digest()
                    or any(getattr(episode, key) != getattr(request, key) for key in (
                        "contract_sha256", "evaluator_sha256", "environment_sha256",
                        "memory_snapshot_sha256", "solver_id"))):
                raise RSILearningError("rsi_transfer_checkpoint_corrupt")
            if stage == "verifier":
                self._validate_verifier_result(clean_result, episode, request, saved_result)
            else:
                if (set(clean_result) != {"accepted", "diagnosis"}
                        or type(clean_result["accepted"]) is not bool):
                    raise RSILearningError("rsi_transfer_judgment_invalid")
                _bounded_text(clean_result["diagnosis"], "transfer_judgment")
                if state.get("execution") is None:
                    raise RSILearningError("rsi_transfer_checkpoint_corrupt")
                execution = RSILearningController._deserialize_execution(state["execution"])
                self._validate_execution(execution, request, internal_id)
                if execution.result != saved_result or execution.episode != episode:
                    raise RSILearningError("rsi_transfer_checkpoint_corrupt")
                if clean_result["accepted"] and not execution.passed:
                    raise RSILearningError("rsi_transfer_judgment_invalid")
            budget = RSIRunBudget.load(state["budget_state"])
            budget.reserve_unknown_reconcile_evidence()
            reconciliation.update(episode_record_sha256=head.record_sha256,
                                  solver_result_sha256=_record_digest(saved_result.to_dict()))
            state.setdefault("callback_reconciliations", {})[stage] = reconciliation
            state.update({field: clean_result, "budget_state": budget.to_dict(),
                          "phase": "verified" if stage == "verifier" else "judged"})
            return self.ledger.write_transfer_reconciliation_checkpoint(
                internal_id, state, expected_sha256=current,
                episode_id=request.episode_id, expected_episode_sha256=head.record_sha256,
            )

    def reconcile_receipt(
        self, run_id: str, target_id: str, *, expected_record_sha256: str,
        evidence: Mapping[str, Any],
    ) -> RSIRecord:
        """Append a failed revision after explicit failure settlement of an unknown worker."""
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        internal_id = self._identity(run_id, target_id)
        with self.ledger.controller_lock(internal_id):
            current, state, request = self._reconcile_state(run_id, target_id)
            published = self.ledger.get_transfer(run_id, target_id)
            if published is None:
                raise RSILearningError("rsi_record_missing")
            previous = published.payload.get("reconciliation")
            if previous is not None:
                if (previous.get("parent_record_sha256") == expected_record_sha256
                        and previous.get("evidence") == evidence):
                    self.ledger.validate_transfer_reconciliation(published)
                    if (state.get("receipt") != published.payload
                            or state.get("receipt_reconciliation") != previous):
                        raise RSILearningError("rsi_transfer_checkpoint_corrupt")
                    return published
                raise RSILearningError("rsi_transfer_reconcile_conflict")
            if published.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            if published.state != "unknown" or state.get("receipt") != published.payload:
                raise RSILearningError("rsi_transfer_receipt_reconcile_not_required")
            head = self.ledger.get_episode(request.episode_id)
            journals = self.ledger.episode_reconciliation(request.episode_id)
            if (head is None or head.state not in {"failed", "cancelled", "timed_out", "abandoned"}
                    or not journals or journals[-1]["worker_state"] != head.state
                    or head.parent_record_sha256 != journals[-1]["parent_record_sha256"]):
                raise RSILearningError("rsi_unknown_reconcile_required")
            if (not isinstance(evidence, Mapping) or set(evidence) != {
                "source", "receipt_record_sha256", "episode_record_sha256", "journal_sha256",
            } or evidence.get("receipt_record_sha256") != expected_record_sha256
                    or evidence.get("episode_record_sha256") != head.record_sha256
                    or evidence.get("journal_sha256") != journals[-1]["journal_sha256"]):
                raise RSILearningError("rsi_transfer_reconcile_evidence_invalid")
            _bounded_text(evidence["source"], "reconcile_source")
            original = RSILearningController._deserialize_execution(state["execution"])
            self._validate_execution(original, request, internal_id)
            saved = self.ledger.episode_result(request.episode_id)
            if (original.result.status != "unknown" or saved is None
                    or saved != (request, original.result)):
                raise RSILearningError("rsi_transfer_checkpoint_corrupt")
            episode = PracticeEpisode.from_dict(head.payload)
            result = replace(original.result, status=head.state, terminal_reason=episode.terminal_reason)
            decision = VerifierDecision(
                episode.episode_id, "unresolved", journals[-1]["journal_sha256"],
                "worker explicitly reconciled to " + head.state,
                _record_digest({"verifier": "reconciled-transfer-failure-v1"}),
                (VerifierCheck("terminal_failure", "unresolved", journals[-1]["journal_sha256"]),),
                contract_sha256=request.contract_sha256, evaluator_sha256=request.evaluator_sha256,
                environment_sha256=request.environment_sha256,
            )
            execution = EpisodeExecution(episode, request, result, decision)
            self._validate_execution(execution, request, internal_id)
            receipt = replace(self._receipt(published.payload), status="failed")
            budget = RSIRunBudget.load(state["budget_state"])
            budget.reserve_unknown_reconcile_evidence()
            metadata = {
                "parent_record_sha256": expected_record_sha256,
                "episode_id": request.episode_id, "episode_record_sha256": head.record_sha256,
                "journal_sha256": journals[-1]["journal_sha256"], "evidence": dict(evidence),
            }
            state.update(phase="terminal", execution=RSILearningController._serialize_execution(execution),
                         receipt=receipt.to_dict() | {"reconciliation": metadata},
                         budget_state=budget.to_dict(), receipt_reconciliation=metadata)
            return self.ledger.reconcile_transfer_receipt(
                receipt, internal_run_id=internal_id, expected_record_sha256=expected_record_sha256,
                reconciliation=metadata, state=state, expected_checkpoint_sha256=current,
            )

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
        internal_id = self._identity(run_id, target_id)
        episode_id = internal_id + "-target" if self.ledger is not None else target_id
        request = SolverRequest.build(
            episode_id=episode_id, contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256, environment_sha256=environment_sha256,
            memory_snapshot_sha256=snapshot.digest(), solver_id=solver_id, budget=budget,
            practice_charter={"curriculum_enabled": False, "memory_write_enabled": False},
        )
        episode = PracticeEpisode(
            episode_id, internal_id if self.ledger is not None else run_id,
            contract_sha256, evaluator_sha256, environment_sha256,
            snapshot.digest(), solver_id, "planned", episode_kind="target",
        )
        if self.ledger is None:
            run_budget = RSIRunBudget.create(budget)
            run_budget.reserve_launch_with_stages(
                episode_kind="target", depth=0, ancestry=(episode_id,),
                stages=("evaluator", "verifier", "transfer"),
            )
            runner = self

            class BudgetVerifier:
                def verify(self, episode, request, result):
                    run_budget.check()
                    return runner.verifier.verify(episode, request, result)

            execution = PracticeEpisodeRunner(self.gateway, BudgetVerifier()).run(episode, request)
            run_budget.check()
            accepted, _diagnosis = self.target_judge(execution)
            return self._make_receipt(run_id, target_id, snapshot, execution, accepted), execution
        with self.ledger.controller_lock(internal_id):
            return self._run_locked(internal_id, run_id, target_id, snapshot, episode, request, budget)

    def _run_locked(self, internal_id: str, run_id: str, target_id: str, snapshot: MemorySnapshot,
                    episode: PracticeEpisode, request: SolverRequest,
                    budget: Mapping[str, Any] | None) -> tuple[TransferReceipt, EpisodeExecution]:
        ledger = self.ledger
        components = {
            "gateway": _component_digest(self.gateway, name="solver"),
            "verifier": _component_digest(self.verifier, name="verifier"),
            "judge": _component_digest(self.target_judge, name="target_judge"),
        }
        intent = {
            "run_id": run_id, "target_id": target_id, "request": request.to_dict(),
            "snapshot": snapshot.to_dict(), "components": components,
        }
        previous = ledger.controller_checkpoint(internal_id)
        published = ledger.get_transfer(run_id, target_id)
        if previous is None:
            if published is not None:
                # An old receipt without an execution journal cannot prove which verifier/judge
                # side effects finished; leave it read-only for explicit migration/reconciliation.
                raise RSILearningError("rsi_transfer_recovery_required")
            run_budget = RSIRunBudget.create(budget)
            run_budget.reserve_launch_with_stages(
                episode_kind="target", depth=0, ancestry=(episode.episode_id,),
                stages=("evaluator", "verifier", "transfer"),
            )
            state = {
                "schema_version": "1", "kind": "rsi_transfer_checkpoint", "intent": intent,
                "budget_policy": dict(budget or {}), "budget_state": run_budget.to_dict(),
                "phase": "prepared", "verifier_started": False, "verifier": None,
                "judge_started": False, "judgment": None, "execution": None, "receipt": None,
            }
        else:
            state = previous[1]
            if state.get("kind") != "rsi_transfer_checkpoint" or state.get("schema_version") != "1":
                raise RSILearningError("rsi_transfer_checkpoint_corrupt")
            if state.get("budget_policy") != dict(budget or {}):
                raise RSILearningError("rsi_resume_budget_drift")
            if state.get("intent") != intent:
                raise RSILearningError("rsi_transfer_fingerprint_drift")
            _validated_digest, state, _validated_request = self._reconcile_state(run_id, target_id)
            run_budget = RSIRunBudget.load(state["budget_state"])
            run_budget.assert_matches(budget)
        checkpoint_digest = previous[0] if previous else None

        def checkpoint() -> None:
            nonlocal checkpoint_digest
            checkpoint_digest = ledger.write_controller_checkpoint(
                internal_id, state, expected_sha256=checkpoint_digest,
            )

        if published is not None:
            if state.get("execution") is None or state.get("receipt") != published.payload:
                raise RSILearningError("rsi_transfer_checkpoint_corrupt")
            execution = RSILearningController._deserialize_execution(state["execution"])
            self._validate_execution(execution, request, internal_id)
            if "reconciliation" in published.payload:
                ledger.validate_transfer_reconciliation(published)
                if state.get("receipt_reconciliation") != published.payload["reconciliation"]:
                    raise RSILearningError("rsi_transfer_checkpoint_corrupt")
            if published.state == "unknown":
                head = ledger.get_episode(episode.episode_id)
                if head is None or head.state != "unknown":
                    # The published receipt is immutable. An explicit worker reconciliation must
                    # not silently rewrite this old unknown transfer into a passed receipt.
                    raise RSILearningError("rsi_transfer_unknown_receipt_reconcile_required")
            return self._receipt(published.payload), execution
        # Once the judgment is durably stored, only local receipt publication remains.  Finalize
        # that same result even if the original deadline has elapsed; no callback is repeated.
        if state["judgment"] is None:
            run_budget.check()
        if previous is None:
            checkpoint()
        runner = self

        class DurableVerifier:
            def verify(self, episode, request, result):
                if state["verifier"] is not None:
                    return runner._verdict(state["verifier"])
                if state["verifier_started"]:
                    raise RSILearningError("rsi_transfer_verifier_reconcile_required")
                run_budget.check()
                state.update(phase="verifying", verifier_started=True)
                checkpoint()
                decision = runner.verifier.verify(episode, request, result)
                state.update(phase="verified", verifier=decision.to_dict())
                checkpoint()
                return decision

        verifier = DurableVerifier()
        if state["execution"] is not None:
            execution = RSILearningController._deserialize_execution(state["execution"])
        else:
            head = ledger.get_episode(episode.episode_id)
            if head is None:
                execution = PracticeEpisodeRunner(self.gateway, verifier, ledger).run(episode, request)
            else:
                persisted = ledger.episode_result(episode.episode_id)
                if persisted is None:
                    raise RSILearningError("rsi_unknown_reconcile_required" if head.state == "unknown"
                                           else "rsi_resume_recovery_required")
                saved_request, result = persisted
                if saved_request.to_dict() != request.to_dict():
                    raise RSILearningError("rsi_transfer_fingerprint_drift")
                recovered = PracticeEpisode.from_dict(head.payload)
                if (
                    recovered.run_id != internal_id
                    or recovered.episode_id != request.episode_id
                    or recovered.request_sha256 != request.digest()
                    or recovered.solver_id != request.solver_id
                    or recovered.contract_sha256 != request.contract_sha256
                    or recovered.evaluator_sha256 != request.evaluator_sha256
                    or recovered.environment_sha256 != request.environment_sha256
                    or recovered.memory_snapshot_sha256 != request.memory_snapshot_sha256
                ):
                    raise RSILearningError("rsi_transfer_fingerprint_drift")
                if head.state in {"running", "unknown"} and not (head.state == result.status == "unknown"):
                    head = ledger.reconcile_episode(
                        episode.episode_id, worker_state=result.status, result=result,
                        expected_record_sha256=head.record_sha256,
                        evidence={"reconciliation": {"source": "persisted_transfer_result",
                                                     "request_sha256": request.digest()}},
                    )
                    recovered = PracticeEpisode.from_dict(head.payload)
                if recovered.status != result.status:
                    raise RSILearningError("rsi_unknown_reconcile_required")
                decision = recovered.verifier or verifier.verify(recovered, request, result)
                if recovered.status == "completed" and recovered.verifier is None:
                    recovered = recovered.attach_verifier(decision)
                    ledger.append_episode_record(recovered, expected_record_sha256=head.record_sha256)
                execution = EpisodeExecution(recovered, request, result, decision)
            state.update(phase="evaluated", execution=RSILearningController._serialize_execution(execution))
            checkpoint()
        self._validate_execution(execution, request, internal_id)
        if state["judgment"] is None:
            if state["judge_started"]:
                raise RSILearningError("rsi_transfer_judge_reconcile_required")
            run_budget.check()
            state.update(phase="judging", judge_started=True)
            checkpoint()
            accepted, diagnosis = self.target_judge(execution)
            if type(accepted) is not bool or type(diagnosis) is not str:
                raise RSILearningError("rsi_transfer_judgment_invalid")
            state.update(phase="judged", judgment={"accepted": accepted, "diagnosis": diagnosis})
            checkpoint()
        receipt = self._make_receipt(run_id, target_id, snapshot, execution, state["judgment"]["accepted"])
        if state["receipt"] is not None and state["receipt"] != receipt.to_dict():
            raise RSILearningError("rsi_transfer_checkpoint_corrupt")
        if state["receipt"] is None:
            state.update(phase="publishing", receipt=receipt.to_dict())
            checkpoint()
        ledger.create_transfer_receipt(receipt)
        state.update(phase="terminal")
        checkpoint()
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
        usage_ledger: RSIUsageLedger | None = None,
        memory_admission_gate: Any | None = None,
        generation_regression_tasks: Sequence[Any] | None = None,
        generation_regression_runner: Callable[..., Any] | None = None,
        generation_revalidate_before_dispatch: bool = False,
    ) -> None:
        self.gateway = gateway
        self.verifier = verifier or LocalExactVerifier()
        self.curriculum = curriculum or DeterministicCurriculum()
        self.memory_store = memory_store or RSIMemoryStore(EMPTY_MEMORY_SNAPSHOT)
        self.target_judge = target_judge
        self.ledger = ledger
        if usage_ledger is not None and not isinstance(usage_ledger, RSIUsageLedger):
            raise TypeError("usage_ledger must be an RSI usage UsageLedger")
        self.usage_ledger = usage_ledger
        from .rsi_governance_coordinator import RSIGovernanceCoordinator

        if memory_admission_gate is not None:
            from .rsi_memory_snapshot_gate import GovernedMemorySnapshotGate

            if not isinstance(memory_admission_gate, (GovernedMemorySnapshotGate, RSIGovernanceCoordinator)):
                raise TypeError("memory_admission_gate must be a governed snapshot gate or coordinator")
        self.memory_admission_gate = memory_admission_gate
        self.generation_regression_tasks: tuple[Any, ...] = ()
        self.generation_regression_runner = generation_regression_runner
        if type(generation_revalidate_before_dispatch) is not bool:
            raise RSILearningError("rsi_generation_controller_config_invalid")
        self.generation_revalidate_before_dispatch = generation_revalidate_before_dispatch
        if generation_regression_tasks is not None or generation_regression_runner is not None:
            from .rsi_transfer_regression import TransferRegressionSuite, TransferTask

            if (not isinstance(memory_admission_gate, RSIGovernanceCoordinator)
                    or ledger is None or memory_admission_gate.ledger is not ledger
                    or not callable(generation_regression_runner)):
                raise RSILearningError("rsi_generation_controller_config_invalid")
            manifest = TransferRegressionSuite._validate_tasks(
                generation_regression_tasks, memory_admission_gate.policy.regression,
            )
            self.generation_regression_tasks = tuple(TransferTask(**task.to_dict()) for task in manifest)
            _component_digest(generation_regression_runner, name="generation_regression_runner")
        if generation_revalidate_before_dispatch and not self.generation_regression_tasks:
            raise RSILearningError("rsi_generation_controller_config_invalid")
        # Transfer reports are retained only as a local idempotency aid.  The governance
        # admission record remains the durable source of truth; a fresh process may return
        # ``None`` for an already-approved report when the report itself was not persisted.
        self._transfer_promotion_reports: dict[tuple[str, str, str, str], Any] = {}

    @property
    def snapshot(self) -> MemorySnapshot:
        return self.memory_store.snapshot

    def generation_campaign_runner(self, run_id: str) -> Any:
        """Build the exact child campaign used for explicit generation recovery."""
        from .rsi_generation_campaign import GenerationCampaignRunner

        if self.ledger is None or not self.generation_regression_tasks:
            raise RSILearningError("rsi_generation_controller_config_invalid")

        return GenerationCampaignRunner(
            self.ledger, run_id, tasks=self.generation_regression_tasks,
            runner=self.generation_regression_runner, component_pins=self._generation_component_pins,
        )

    def _generation_component_pins(self) -> dict[str, str]:
        components = {"solver": self.gateway, "verifier": self.verifier, "curriculum": self.curriculum,
                      "judge": self.target_judge, "governance": self.memory_admission_gate,
                      "runner": self.generation_regression_runner}
        return {**{name: _component_digest(value, name=name) for name, value in components.items()},
                "manifest": _record_digest([task.to_dict() for task in self.generation_regression_tasks])}

    def _generation_campaign_config_readonly(self, parent_run_id: str) -> dict[str, Any]:
        """Project the same helper identity without acquiring a controller-owned parent lock."""
        if self.ledger is None:
            raise RSILearningError("rsi_generation_controller_config_invalid")
        parent = self.ledger.get_run(parent_run_id)
        if parent is None:
            raise RSILearningError("rsi_parent_budget_missing")
        identity = self.ledger.database.stat()
        return {"protocol": "rsi-generation-campaign-v1", "parent": {
            "run_id": parent_run_id, "request_sha256": parent.request_sha256,
            "ledger": str(self.ledger.database), "device": identity.st_dev, "inode": identity.st_ino,
            "planned_budget": RSIRunBudget.load(parent.payload["budget_state"]).to_dict()["planned"],
        }, "manifest": [task.to_dict() for task in self.generation_regression_tasks],
            "runner": _component_digest(self.generation_regression_runner, name="generation_regression_runner"),
            "components": self._generation_component_pins()}

    def promote_transfer_regression(
        self,
        *,
        governance: Any,
        admission_id: str,
        expected_record_sha256: str,
        old_memory: MemorySnapshot,
        tasks: Sequence[Any],
        runner: Callable[..., Any],
        policy: Any | None = None,
        activate: bool = False,
        fingerprints: Mapping[str, object] | None = None,
        budget: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> tuple[Any | None, Any]:
        """Run local transfer regression and apply the explicit memory promotion gate.

        This is deliberately opt-in and provider-free.  ``old_memory`` and the controller's
        current immutable snapshot are the only memories passed to the regression suite; the
        suite runner is supplied by the caller and must return its local observations.  The
        governance adapter performs the final CAS and ``shadow -> approved`` (optionally
        ``approved -> active``) transitions.  No ``RSIMemoryStore`` mutation is performed.

        A second call after approval/activation is an idempotent read.  It does not execute the
        suite again or append another governance revision; when this controller still has the
        original report it is returned, otherwise the report slot is ``None``.
        """
        # Lazy imports keep the controller's core execution path independent from the optional
        # governance/transfer modules and avoid making this composition mandatory for DRS/BRS.
        from .rsi_memory_governance import MemoryGovernanceStore
        from .rsi_memory_promotion import MemoryPromotionAdapter, MemoryPromotionError
        from .rsi_parent_budget import ParentRunBudget
        from .rsi_regression_campaign import DurableRegressionCampaign
        from .rsi_transfer_regression import TransferRegressionSuite

        if not isinstance(governance, MemoryGovernanceStore):
            raise MemoryPromotionError("rsi_memory_promotion_governance_invalid")
        if type(admission_id) is not str or not admission_id.strip():
            raise MemoryPromotionError("rsi_memory_promotion_admission_invalid")
        if type(expected_record_sha256) is not str or len(expected_record_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in expected_record_sha256
        ):
            raise MemoryPromotionError("rsi_memory_promotion_expected_record_invalid")
        if not isinstance(old_memory, MemorySnapshot):
            raise MemoryPromotionError("rsi_memory_promotion_memory_invalid")
        if type(activate) is not bool:
            raise MemoryPromotionError("rsi_memory_promotion_activate_invalid")
        suite = TransferRegressionSuite(policy=policy)
        manifest = suite._validate_tasks(tasks, suite.policy)
        planned_budget = RSIRunBudget.create(budget)
        parent_budget = None
        if parent_run_id is not None:
            if self.ledger is None:
                raise RSILearningError("rsi_parent_budget_requires_ledger")
            parent_budget = ParentRunBudget(self.ledger, parent_run_id)
            parent_budget.identity()
        if fingerprints is not None and (
            not isinstance(fingerprints, Mapping) or any(type(key) is not str for key in fingerprints)
        ):
            raise MemoryPromotionError("rsi_memory_promotion_fingerprint_invalid")

        admission = governance.get(admission_id)
        if admission is None:
            raise MemoryPromotionError("rsi_memory_governance_missing")
        if admission.record_sha256 != expected_record_sha256:
            raise MemoryPromotionError("rsi_memory_governance_cas_conflict")
        if admission.state == "revoked":
            raise MemoryPromotionError("rsi_memory_governance_revoked")
        if admission.state not in {"shadow", "approved", "active"}:
            raise MemoryPromotionError("rsi_memory_governance_transition_invalid")

        # A candidate admission is bound to exactly the frozen current snapshot.  The parent
        # digest is also checked before spending any holdout calls, including the empty parent
        # convention used by the governance adapter.
        current_memory = self.snapshot
        if admission.memory_snapshot_sha256 != current_memory.digest():
            raise MemoryPromotionError("rsi_memory_promotion_snapshot_drift")
        expected_parent = old_memory.digest()
        if (admission.parent_snapshot_sha256 or EMPTY_MEMORY_SNAPSHOT_SHA256) != expected_parent:
            raise MemoryPromotionError("rsi_memory_promotion_snapshot_drift")

        def component_pins() -> dict[str, object]:
            pins: dict[str, object] = {
                "memory_snapshot_sha256": self.snapshot.digest(),
                "solver_fingerprint": _component_digest(self.gateway, name="solver"),
                "verifier_fingerprint": _component_digest(self.verifier, name="verifier"),
                "curriculum_fingerprint": _component_digest(self.curriculum, name="curriculum"),
                "target_judge_fingerprint": _component_digest(self.target_judge, name="target_judge"),
            }
            if self.memory_admission_gate is not None:
                pins["memory_admission_gate_fingerprint"] = _component_digest(self.memory_admission_gate, name="memory_admission_gate")
            if parent_budget is not None:
                pins["parent_budget_identity"] = parent_budget.identity()
            return pins

        observed_fingerprints = component_pins()
        try:
            supplied_fingerprints = json.loads(canonical_json(dict(fingerprints or {}), maximum=128 * 1024))
            supplied_digest = _record_digest(supplied_fingerprints)
        except Exception as exc:
            raise MemoryPromotionError("rsi_memory_promotion_fingerprint_invalid") from exc
        # Caller-owned external pins may supplement component identity, but cannot replace the
        # controller's independent observations with stale or fabricated component digests.
        for key, value in supplied_fingerprints.items():
            if key in observed_fingerprints and value != observed_fingerprints[key]:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift")
        pinned_components = dict(observed_fingerprints)
        observed_fingerprints.update(supplied_fingerprints)
        for key, value in observed_fingerprints.items():
            declared = admission.compatibility.get(key)
            if declared is not None and declared != value:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift")
        try:
            approval_reason = "controller_transfer_promotion_v2:" + _record_digest({
                "fingerprints": observed_fingerprints,
                "old_memory_sha256": old_memory.digest(),
                "manifest": [task.to_dict() for task in manifest],
                "policy": suite.policy.to_dict(),
                "planned_budget": planned_budget.to_dict()["planned"],
            })
        except Exception as exc:
            raise MemoryPromotionError("rsi_memory_promotion_fingerprint_invalid") from exc
        if admission.state in {"approved", "active"}:
            if admission.reason is None or not admission.reason.startswith("controller_transfer_promotion_v2:"):
                raise MemoryPromotionError("rsi_memory_promotion_identity_missing")
            if admission.reason != approval_reason:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift")

        def report_key(head: Any) -> tuple[str, str, str, str]:
            return (str(governance.database), head.admission_id,
                    head.holdout_receipt_sha256 or "", head.baseline_receipt_sha256 or "")

        def cached_report() -> Any | None:
            report = self._transfer_promotion_reports.get(report_key(admission))
            if report is not None and (
                report.current_memory_sha256 != current_memory.digest()
                or report.old_memory_sha256 != old_memory.digest()
                or report.holdout_receipt_sha256 != admission.holdout_receipt_sha256
                or report.baseline_receipt_sha256 != admission.baseline_receipt_sha256
            ):
                raise MemoryPromotionError("rsi_memory_promotion_report_drift")
            return report

        # Do not rerun a completed promotion.  CAS is checked above so a caller cannot turn an
        # old expected digest into an idempotent success after another process changed the head.
        if admission.state == "active":
            return cached_report(), admission
        if admission.state == "approved" and not activate:
            return cached_report(), admission
        if admission.state == "approved" and activate:
            retained_report = cached_report()
            if retained_report is None:
                promoted = MemoryPromotionAdapter(governance).activate_approved(
                    admission_id,
                    expected_record_sha256=expected_record_sha256,
                    compatibility=admission.compatibility,
                )
                return None, promoted
            promoted = MemoryPromotionAdapter(governance).promote(
                admission_id,
                retained_report,
                expected_record_sha256=expected_record_sha256,
                compatibility=admission.compatibility,
                activate=True,
                approval_reason=approval_reason,
            )
            return retained_report, promoted

        def check_components() -> None:
            if self.snapshot.digest() != current_memory.digest():
                raise MemoryPromotionError("rsi_memory_promotion_snapshot_drift")
            if component_pins() != pinned_components:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift")
            try:
                external_digest = _record_digest(dict(fingerprints or {}))
            except Exception as exc:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift") from exc
            if external_digest != supplied_digest:
                raise MemoryPromotionError("rsi_memory_promotion_fingerprint_drift")

        if not callable(runner):
            raise MemoryPromotionError("rsi_memory_promotion_runner_invalid")

        def checked_runner(task: Any, memory: MemorySnapshot, repetition: int) -> Any:
            check_components()
            if self.ledger is None:
                planned_budget.reserve_stages(("transfer", "evaluator"))
            result = runner(task, memory, repetition)
            check_components()
            return result

        if self.ledger is not None:
            report = DurableRegressionCampaign(self.ledger).run(
                admission_id=admission_id, initial_record_sha256=expected_record_sha256,
                tasks=manifest, old_memory=old_memory, current_memory=current_memory,
                runner=runner, policy=suite.policy, controller_pins=observed_fingerprints,
                check_components=check_components, budget=budget,
                parent_budget=parent_budget,
            )
        else:
            report = suite.run(
                manifest, old_memory=old_memory, current_memory=current_memory, runner=checked_runner,
            )
            planned_budget.check()
        # A malicious or accidental runner must not mutate the controller's memory between the
        # frozen suite and the governance write.
        check_components()
        promoted = MemoryPromotionAdapter(governance).promote(
            admission_id,
            report,
            expected_record_sha256=expected_record_sha256,
            compatibility=admission.compatibility,
            activate=activate,
            approval_reason=approval_reason,
        )
        self._transfer_promotion_reports[report_key(promoted)] = report
        return report, promoted

    def _failure_curriculum_state(self) -> dict[str, Any] | None:
        """Return optional mutable failure-driven curriculum state for a run checkpoint."""

        # Import lazily because rsi_curriculum imports CurriculumDecision from this module.
        from .rsi_curriculum import FailureDrivenCurriculum

        if not isinstance(self.curriculum, FailureDrivenCurriculum):
            return None
        try:
            ledger = list(self.curriculum.to_ledger())
            seed = self.curriculum.seed
            budget = self.curriculum.budget_limit
            policy = self.curriculum.policy.to_dict()
            digest = self.curriculum.ledger_digest()
        except (AttributeError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_curriculum_checkpoint_invalid") from exc
        return {
            "protocol": "rsi-failure-driven-curriculum-v1",
            "seed": seed,
            "budget": budget,
            "policy": policy,
            "ledger": ledger,
            "ledger_digest": digest,
        }

    def _restore_failure_curriculum(self, state: Mapping[str, Any]) -> None:
        """Restore failure-driven ledger state before any resumed callback executes."""

        raw = state.get("curriculum_state")
        if raw is None:
            return
        from .rsi_curriculum import FailureBoundaryPolicy, FailureDrivenCurriculum

        if not isinstance(self.curriculum, FailureDrivenCurriculum):
            raise RSILearningError("rsi_resume_curriculum_drift")
        if (not isinstance(raw, Mapping)
                or not {"protocol", "seed", "budget", "ledger", "ledger_digest"}.issubset(raw)
                or set(raw) - {"protocol", "seed", "budget", "policy", "ledger", "ledger_digest"}
                or raw.get("protocol") != "rsi-failure-driven-curriculum-v1"):
            raise RSILearningError("rsi_curriculum_checkpoint_corrupt")
        try:
            current_policy = self.curriculum.policy
            # A legacy checkpoint predates configurable policies and therefore has the fixed
            # default policy.  Never reinterpret it under a caller's custom policy.
            checkpoint_policy = FailureBoundaryPolicy.from_dict(raw["policy"]) if "policy" in raw else FailureBoundaryPolicy()
            if checkpoint_policy.to_dict() != current_policy.to_dict():
                raise RSILearningError("rsi_resume_curriculum_drift")
            restored = FailureDrivenCurriculum.from_ledger(
                raw["ledger"], seed=raw["seed"], budget=raw["budget"], policy=current_policy,
            )
            # The legacy digest covered only seed/budget/ledger.  Accept that exact formula
            # only when the checkpoint has no configurable policy field.
            expected_digest = restored.ledger_digest() if "policy" in raw else _record_digest({
                "seed": restored.seed, "budget": restored.budget_limit, "ledger": list(restored.to_ledger()),
            })
            if expected_digest != raw["ledger_digest"]:
                raise RSILearningError("rsi_curriculum_checkpoint_corrupt")
            if (restored.seed != self.curriculum.seed
                    or restored.budget_limit != self.curriculum.budget_limit
                    or restored.policy.to_dict() != current_policy.to_dict()):
                raise RSILearningError("rsi_resume_curriculum_drift")
        except RSILearningError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise RSILearningError("rsi_curriculum_checkpoint_corrupt") from exc
        self.curriculum = restored

    def _sync_curriculum_checkpoint(self, state: dict[str, Any]) -> None:
        curriculum_state = self._failure_curriculum_state()
        if curriculum_state is not None:
            state["curriculum_state"] = curriculum_state

    def callback_checkpoint(self, run_id: str, callback_id: str) -> tuple[str, dict[str, Any]] | None:
        """Inspect one durable callback without executing it or changing the learning run."""
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        return DurableCallbackJournal(self.ledger).inspect(run_id, callback_id)

    @staticmethod
    def _callback_result(binding: Mapping[str, Any], value: Mapping[str, Any]) -> None:
        """Validate an observed callback result against its original, persisted inputs."""
        try:
            stage, inputs = binding["stage"], binding["input"]
            if stage == "verifier":
                request = SolverRequest.from_dict(inputs["request"])
                result = SolverResult.from_dict(inputs["result"])
                raw = dict(value)
                raw["checks"] = tuple(VerifierCheck(**item) for item in raw["checks"])
                decision = VerifierDecision(**raw)
                if decision.to_dict() != value or decision.episode_id != request.episode_id:
                    raise ValueError("verifier identity")
                if any(getattr(decision, key) != getattr(request, key) for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256",
                )) or any(getattr(decision, key) != getattr(result, key) for key in (
                    "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                )):
                    raise ValueError("verifier pins")
                evidence = {key: getattr(result, key) for key in (
                    "candidate_receipt_sha256", "execution_receipt_sha256",
                    "official_evaluation_receipt_sha256", "trace_digest",
                )}
                if decision.evidence_sha256 != _record_digest(evidence):
                    raise ValueError("verifier evidence")
                if decision.outcome == "pass" and (result.status != "completed" or any(
                    getattr(result, key) is None for key in (
                        "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                    )
                )):
                    raise ValueError("unverified success")
            elif stage == "judge":
                execution = RSILearningController._deserialize_execution(inputs["execution"])
                if (set(value) != {"accepted", "diagnosis"} or type(value["accepted"]) is not bool
                        or type(value["diagnosis"]) is not str or not value["diagnosis"].strip()
                        or len(value["diagnosis"].encode()) > 8192
                        or (value["accepted"] and not execution.passed)):
                    raise ValueError("judgment")
            elif stage == "curriculum":
                decision = RSILearningController._decision_from_dict(value)
                target = PracticeEpisode.from_dict(inputs["target"])
                if decision.to_dict() != value or target.solver_id not in decision.compatible_solvers:
                    raise ValueError("curriculum")
            else:
                raise ValueError("callback stage")
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_callback_result_invalid") from exc

    def _callback_binding(self, stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        component = {"verifier": self.verifier, "judge": self.target_judge, "curriculum": self.curriculum}[stage]
        return {"stage": stage, "input": dict(inputs),
                "component_sha256": _component_digest(component, name=stage)}

    def _invoke_callback(self, run_id: str, callback_id: str, stage: str, inputs: Mapping[str, Any],
                         call: Callable[[], Mapping[str, Any]],
                         before_call: Callable[[], None] | None = None) -> dict[str, Any]:
        if self.ledger is None:
            if before_call is not None:
                before_call()
            result = dict(call())
            self._callback_result({"stage": stage, "input": inputs}, result)
            return result
        binding = self._callback_binding(stage, inputs)
        return DurableCallbackJournal(self.ledger).invoke(
            run_id, callback_id, binding=binding, call=call,
            validate=lambda value: self._callback_result(binding, value), before_call=before_call,
        )

    def _verify_episode(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult,
                        before_call: Callable[[], None] | None = None) -> VerifierDecision:
        if result.status != "completed":
            # A failure diagnosis cannot promote memory and needs no external verification.
            # In particular, settling an unknown worker does not repeat a verifier callback.
            return LocalExactVerifier().verify(episode, request, result)
        value = self._invoke_callback(
            episode.run_id, f"verifier:{episode.episode_id}", "verifier",
            {"request": request.to_dict(), "result": result.to_dict()},
            lambda: self.verifier.verify(episode, request, result).to_dict(), before_call,
        )
        raw = dict(value)
        raw["checks"] = tuple(VerifierCheck(**item) for item in raw["checks"])
        return VerifierDecision(**raw)

    def _callback_binding_for_run(self, state: Mapping[str, Any], callback_id: str) -> dict[str, Any]:
        stage, separator, episode_id = callback_id.partition(":")
        if not separator or stage not in {"verifier", "judge", "curriculum"}:
            raise RSILearningError("rsi_callback_identity_invalid")
        if stage == "verifier":
            intent = state["intents"].get(episode_id)
            saved = self.ledger.episode_result(episode_id)
            head = self.ledger.get_episode(episode_id)
            if (intent is None or saved is None or head is None or head.state != "completed"
                    or head.payload["run_id"] != state["run_id"] or saved[0].to_dict() != intent["request"]
                    or saved[1].status != "completed"):
                raise RSILearningError("rsi_callback_input_mismatch")
            inputs = {"request": saved[0].to_dict(), "result": saved[1].to_dict()}
        elif stage == "judge":
            execution = state["executions"].get(episode_id)
            if execution is None or execution["episode"]["episode_kind"] != "target":
                raise RSILearningError("rsi_callback_input_mismatch")
            inputs = {"execution": execution}
        else:
            inputs = None
            for target_id, execution in state["executions"].items():
                target = PracticeEpisode.from_dict(execution["episode"])
                if (target.episode_kind == "target" and
                        episode_id == f"{state['run_id']}-practice-{target.wave}-0"
                        and target_id in state["judgments"]):
                    inputs = {"target": target.to_record_dict(), "diagnosis": state["judgments"][target_id][1],
                              "wave": target.wave, "ordinal": 0}
                    break
            if inputs is None:
                raise RSILearningError("rsi_callback_input_mismatch")
        return self._callback_binding(stage, inputs)

    def reconcile_callback(self, run_id: str, callback_id: str, *, expected_checkpoint_sha256: str,
                           result: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Record an explicit callback result; never retry the uncertain external operation."""
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        with self.ledger.controller_lock(run_id):
            record = self.ledger.get_run(run_id)
            checkpoint = self.ledger.controller_checkpoint(run_id)
            if record is None or checkpoint is None or checkpoint[1].get("schema_version") != "2":
                raise RSILearningError("rsi_resume_checkpoint_unavailable")
            self._validate_resume_identity(record, None, None)
            self._check_budget_history(record)
            state = checkpoint[1]
            self._restore_failure_curriculum(state)
            if state.get("callback_protocol_version") != "1":
                raise RSILearningError("rsi_callback_migration_required")
            binding = self._callback_binding_for_run(state, callback_id)
            self._callback_result(binding, result)
            journal = DurableCallbackJournal(self.ledger)
            clean_evidence = journal.validate_evidence(binding, result, evidence)
            callback = journal.inspect(run_id, callback_id)
            if callback is None:
                raise RSILearningError("rsi_callback_missing")
            if callback[1]["binding"] != binding:
                raise RSILearningError("rsi_callback_binding_drift")
            if callback[1]["status"] == "completed":
                return journal.reconcile(
                    run_id, callback_id, expected_checkpoint_sha256=expected_checkpoint_sha256,
                    binding=binding, result=result, evidence=clean_evidence,
                    validate=lambda value: self._callback_result(binding, value),
                )
            if callback[0] != expected_checkpoint_sha256:
                raise RSILearningError("rsi_callback_checkpoint_conflict")
            if record.state in {"completed", "failed", "cancelled", "budget_exhausted"}:
                raise RSILearningError("rsi_callback_terminal_run")
            reservation = {"checkpoint_sha256": expected_checkpoint_sha256,
                           "result_sha256": journal.digest(result), "evidence_sha256": journal.digest(clean_evidence)}
            reservations = state.setdefault("callback_reconciliation_reservations", {})
            if callback_id in reservations:
                if reservations[callback_id] != reservation:
                    raise RSILearningError("rsi_callback_checkpoint_conflict")
            else:
                run_budget = RSIRunBudget.load(state["budget_state"])
                run_budget.assert_matches(record.payload["budget"])
                run_budget.reserve_unknown_reconcile_evidence()
                state["budget_state"] = run_budget.to_dict()
                reservations[callback_id] = reservation
                self._save_flow(record, state)
            return journal.reconcile(
                run_id, callback_id, expected_checkpoint_sha256=expected_checkpoint_sha256,
                binding=binding, result=result, evidence=clean_evidence,
                validate=lambda value: self._callback_result(binding, value),
            )

    def _check_callback_quarantine(self, state: Mapping[str, Any]) -> None:
        """Check the entire known wave before recovery performs another callback or merge."""
        for episode_id, intent in state["intents"].items():
            keys = [f"verifier:{episode_id}"]
            if intent["episode"]["episode_kind"] == "target":
                keys.extend((f"judge:{episode_id}",
                             f"curriculum:{state['run_id']}-practice-{intent['episode']['wave']}-0"))
            for key in keys:
                callback = self.callback_checkpoint(state["run_id"], key)
                if callback is not None and callback[1]["status"] == "started":
                    raise RSILearningError("rsi_callback_reconcile_required")

    def _check_budget_history(self, record: RSIRecord) -> None:
        initial_record = self.ledger.history(record.logical_id)[0]
        previous_budget = RSIRunBudget.load(initial_record.payload["budget_state"]).to_dict()
        previous_intents: dict[str, Any] = {}
        checkpoint_history = self.ledger.controller_checkpoint_history(record.logical_id)
        for _, journal_state in checkpoint_history:
            if journal_state.get("schema_version") != "2":
                raise RSILearningError("rsi_resume_checkpoint_corrupt")
            current_budget = RSIRunBudget.load(journal_state["budget_state"]).to_dict()
            if (current_budget["planned"] != previous_budget["planned"]
                    or any(current_budget["consumed"][key] < used
                           for key, used in previous_budget["consumed"].items())):
                raise RSILearningError("rsi_resume_budget_drift")
            if any(journal_state["intents"].get(key) != value for key, value in previous_intents.items()):
                raise RSILearningError("rsi_resume_episode_drift")
            previous_budget, previous_intents = current_budget, journal_state["intents"]
        if checkpoint_history:
            from .rsi_parent_budget import ParentRunBudget

            ParentRunBudget(self.ledger, record.logical_id).validate_history()
        if self.generation_regression_tasks:
            self._check_generation_history(record)

    def _check_generation_history(self, record: RSIRecord) -> None:
        """A hash-valid append cannot erase pending admission or replace frozen candidates."""
        previous: dict[str, Any] = {}
        effective = record.payload["fingerprints"]["memory_snapshot_sha256"]
        for _, state in self.ledger.controller_checkpoint_history(record.logical_id):
            try:
                entries = state.get("generations", {})
                if not isinstance(entries, dict) or set(previous) - set(entries):
                    raise ValueError("deleted generation")
                changes = []
                for key, entry in entries.items():
                    if (set(entry) != {"generation_id", "parent_memory", "candidate_memory", "status", "admission_checkpoint_sha256"}
                            or entry["status"] not in {"pending", "active", "rejected"}
                            or entry["generation_id"] != "controller-generation:" + _record_digest({"run": record.logical_id, "episode": key})):
                        raise ValueError("generation shape")
                    execution = self._deserialize_execution(state["executions"][key])
                    if execution.episode.episode_kind != "practice" or not execution.passed:
                        raise ValueError("source execution")
                    decision_wire = (state["decisions"][key] if state["mode"] == "drs" else
                                     state["plan"]["practices"][execution.episode.ordinal])
                    parent = MemorySnapshot.from_dict(entry["parent_memory"])
                    candidate = MemorySnapshot.from_dict(entry["candidate_memory"])
                    expected = MemorySnapshot(
                        f"snapshot-memory-{key}", parent.digest(),
                        parent.items + (self._memory_item(execution, self._decision_from_dict(decision_wire)),),
                    )
                    persisted = self.ledger.get("memory:" + candidate.snapshot_id)
                    if candidate != expected or persisted is None or persisted.payload != candidate.to_dict():
                        raise ValueError("candidate binding")
                    if entry["status"] == "pending":
                        if entry["admission_checkpoint_sha256"] is not None:
                            raise ValueError("pending authority")
                    else:
                        self._generation_admission_checkpoint(entry, execution)
                    old = previous.get(key)
                    if old is None:
                        if entry["status"] != "pending" or parent.digest() != effective:
                            raise ValueError("new generation")
                        changes.append(entry)
                    elif old != entry:
                        if (old["status"] != "pending" or entry["status"] not in {"active", "rejected"}
                                or {name: value for name, value in old.items() if name not in {"status", "admission_checkpoint_sha256"}}
                                != {name: value for name, value in entry.items() if name not in {"status", "admission_checkpoint_sha256"}}
                                or parent.digest() != effective):
                            raise ValueError("generation drift")
                        changes.append(entry)
                        if entry["status"] == "active":
                            effective = candidate.digest()
                if len(changes) > 1 or MemorySnapshot.from_dict(state["memory_snapshot"]).digest() != effective:
                    raise ValueError("effective generation drift")
                previous = entries
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RSILearningError("rsi_generation_controller_checkpoint_corrupt") from exc

    def _generation_admission_checkpoint(self, entry: Mapping[str, Any], execution: EpisodeExecution) -> None:
        """Verify recorded admission authority while allowing later revocation on read-only replay."""
        coordinator = self.memory_admission_gate
        if coordinator.inspect(entry["generation_id"]) is None:
            raise ValueError("generation missing")
        states = dict(self.ledger.controller_checkpoint_history(coordinator._namespace(entry["generation_id"])))
        authority = states.get(entry["admission_checkpoint_sha256"])
        if (authority is None or authority["phase"] != entry["status"]
                or authority["intent"]["parent_memory"] != entry["parent_memory"]
                or authority["intent"]["current_memory"] != entry["candidate_memory"]
                or authority["intent"]["provenance"][f"memory-{execution.episode.episode_id}"]
                != {"kind": "verified", "verifier": execution.verifier.to_dict()}
                or authority["report"] is None):
            raise ValueError("generation authority drift")
        candidate = MemorySnapshot.from_dict(entry["candidate_memory"])
        if set(authority["heads"]) != {item.memory_id for item in candidate.items}:
            raise ValueError("generation heads incomplete")
        report = coordinator.deserialize_report(authority["report"])
        expected_state = "active" if entry["status"] == "active" else "shadow"
        for item in candidate.items:
            admission_id = authority["intent"]["admissions"][item.memory_id]
            retained = next((record for record in coordinator.governance.history(admission_id)
                             if record.record_sha256 == authority["heads"][item.memory_id]), None)
            if (retained is None or retained.state != expected_state
                    or retained.memory_snapshot_sha256 != candidate.digest()
                    or retained.memory_item_sha256 != _record_digest(item.to_dict())
                    or retained.source_episode_id != item.episode_id
                    or retained.verifier_receipt_sha256 != item.receipt_sha256
                    or retained.parent_snapshot_sha256 != candidate.parent_snapshot_sha256
                    or retained.scope != coordinator.scope
                    or dict(retained.compatibility) != coordinator.rsi_fingerprint_config()["compatibility"]
                    or retained.reason != "generation:" + authority["intent_sha256"]
                    + (":report:" + report.report_sha256 if expected_state == "active" else "")):
                raise ValueError("generation admission drift")
            if expected_state == "active" and (
                not retained.regression_passed
                or retained.holdout_receipt_sha256 != report.holdout_receipt_sha256
                or retained.baseline_receipt_sha256 != report.baseline_receipt_sha256
            ):
                raise ValueError("generation regression drift")

    def _run_fingerprint(
        self,
        *,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        memory_snapshot_sha256: str,
    ) -> tuple[RSIFingerprintContract, str]:
        """Build one complete identity contract for a new or resumed controller run."""

        solver_settings: dict[str, Any] = {}
        if self.memory_admission_gate is not None:
            solver_settings["memory_admission_gate_fingerprint"] = _component_digest(self.memory_admission_gate, name="memory_admission_gate")
        if self.generation_regression_tasks:
            solver_settings["generation_manifest"] = [task.to_dict() for task in self.generation_regression_tasks]
            solver_settings["generation_revalidate_before_dispatch"] = self.generation_revalidate_before_dispatch
            solver_settings["generation_runner_fingerprint"] = _component_digest(
                self.generation_regression_runner, name="generation_regression_runner",
            )
        # The gateway is the executable solver/actor boundary.  Include its source identity and
        # immutable request settings; runtime counters and process state are excluded by the
        # identity helper.
        solver_fingerprint = _component_digest(self.gateway, name="solver")
        actor_fingerprint = solver_fingerprint
        verifier_fingerprint = _component_digest(self.verifier, name="verifier")
        curriculum_fingerprint = _component_digest(self.curriculum, name="curriculum")
        target_judge_fingerprint = _component_digest(self.target_judge, name="target_judge")
        contract = RSIFingerprintContract.build(
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            memory_snapshot_sha256=memory_snapshot_sha256,
            solver_id=solver_id,
            solver_settings=solver_settings,
            actor_fingerprint=actor_fingerprint,
            verifier_fingerprint=verifier_fingerprint,
            curriculum_fingerprint=curriculum_fingerprint,
            target_judge_fingerprint=target_judge_fingerprint,
        )
        return contract, solver_fingerprint

    def _assert_existing_run_request(
        self,
        record: RSIRecord,
        *,
        mode: str,
        contract_sha256: str,
        evaluator_sha256: str,
        environment_sha256: str,
        solver_id: str,
        budget: Mapping[str, Any] | None,
    ) -> None:
        """Reject a terminal-run replay whose request pins differ from its original contract."""
        payload = record.payload
        for key, observed in (
            ("mode", mode),
            ("contract_sha256", contract_sha256),
            ("evaluator_sha256", evaluator_sha256),
            ("environment_sha256", environment_sha256),
            ("solver_id", solver_id),
        ):
            if payload.get(key) != observed:
                raise RSILearningError(f"rsi_resume_{key}_drift")
        if budget is not None and dict(payload.get("budget", {})) != dict(budget):
            raise RSILearningError("rsi_resume_budget_drift")
        stored = payload.get("fingerprints", {}).get("run_fingerprint")
        if isinstance(stored, Mapping):
            expected, _solver_fingerprint = self._run_fingerprint(
                contract_sha256=contract_sha256,
                evaluator_sha256=evaluator_sha256,
                environment_sha256=environment_sha256,
                memory_snapshot_sha256=str(payload.get("fingerprints", {}).get("memory_snapshot_sha256")),
                solver_id=solver_id,
            )
            try:
                ensure_fingerprint_compatible(RSIFingerprintContract.from_dict(stored), expected)
            except Exception as exc:
                raise RSILearningError("rsi_resume_fingerprint_drift") from exc

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
        plan: Mapping[str, Any] | None = None,
    ) -> RSIRecord | None:
        if self.ledger is None:
            return None
        budget_input = dict(budget or {})
        budget_state = RSIRunBudget.create(budget_input)
        run_fingerprint, solver_fingerprint = self._run_fingerprint(
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            memory_snapshot_sha256=self.snapshot.digest(),
            solver_id=solver_id,
        )
        payload = {
            "mode": mode,
            "callback_protocol_version": "1",
            "contract_sha256": contract_sha256,
            "evaluator_sha256": evaluator_sha256,
            "environment_sha256": environment_sha256,
            "solver_id": solver_id,
            "budget": dict(budget or {}),
            "budget_state": budget_state.to_dict(),
            "phase": "created",
            "plan": dict(plan) if plan is not None else None,
            "current_episode_id": None,
            "target_attempts": [],
            "practice_episodes": [],
            "memory_snapshot": self.snapshot.to_dict(),
            "fingerprints": {
                "contract_sha256": contract_sha256,
                "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256,
                "memory_snapshot_sha256": self.snapshot.digest(),
                "solver_fingerprint": solver_fingerprint,
                "run_fingerprint": run_fingerprint.to_dict(),
            },
        }
        curriculum_state = self._failure_curriculum_state()
        if curriculum_state is not None:
            payload["curriculum_state"] = curriculum_state
        request_sha256 = _record_digest({"run_id": run_id, **payload})
        existing = self.ledger.get(run_id)
        if existing is not None:
            if existing.kind != "run":
                raise RSILearningError("rsi_run_identity_conflict")
            for key in ("mode", "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id"):
                if existing.payload.get(key) not in {None, payload.get(key)}:
                    raise RSILearningError("rsi_run_identity_drift")
            if existing.payload.get("budget", payload["budget"]) != payload["budget"]:
                raise RSILearningError("rsi_resume_budget_drift")
            return existing
        created = self.ledger.create_run(run_id, request_sha256, payload)
        return self.ledger.transition(run_id, state="running", expected_record_sha256=created.record_sha256)

    @staticmethod
    def _serialize_execution(execution: EpisodeExecution) -> dict[str, Any]:
        return {
            "episode": execution.episode.to_record_dict(),
            "request": execution.request.to_dict(),
            "result": execution.result.to_dict(),
            "verifier": execution.verifier.to_dict(),
        }

    @staticmethod
    def _deserialize_execution(value: Mapping[str, Any]) -> EpisodeExecution:
        episode = PracticeEpisode.from_dict(value["episode"])
        request = SolverRequest.from_dict(value["request"])
        result = SolverResult.from_dict(value["result"])
        raw_verifier = value["verifier"]
        checks = tuple(
            VerifierCheck(item["name"], item["outcome"], item["receipt_sha256"])
            for item in raw_verifier["checks"]
        )
        verifier = VerifierDecision(
            raw_verifier["episode_id"], raw_verifier["outcome"], raw_verifier["receipt_sha256"],
            raw_verifier["diagnosis"], raw_verifier["verifier_fingerprint"], checks,
            raw_verifier["independent_of_actor"], raw_verifier.get("contract_sha256"),
            raw_verifier.get("evaluator_sha256"), raw_verifier.get("environment_sha256"),
            raw_verifier.get("official_evaluation_receipt_sha256"), raw_verifier.get("evidence_sha256"),
            raw_verifier.get("candidate_receipt_sha256"), raw_verifier.get("execution_receipt_sha256"),
        )
        if (
            episode.episode_id != request.episode_id or result.episode_id != request.episode_id
            or verifier.episode_id != request.episode_id or episode.request_sha256 != request.digest()
            or result.request_sha256 != request.digest() or episode.status != result.status
            or any(getattr(episode, key) != getattr(request, key) for key in (
                "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id",
            ))
            or (episode.verifier is not None and episode.verifier != verifier)
            or any(getattr(verifier, key) not in {None, getattr(request, key)} for key in (
                "contract_sha256", "evaluator_sha256", "environment_sha256",
            ))
            or any(getattr(verifier, key) not in {None, getattr(result, key)} for key in (
                "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
            ))
        ):
            raise RSILearningError("rsi_resume_execution_conflict")
        return EpisodeExecution(episode, request, result, verifier)

    def _resume_episode_execution(
        self, episode_record: RSIRecord, *, request_hint: SolverRequest | None = None,
        before_verify: Callable[[], None] | None = None,
    ) -> EpisodeExecution:
        """Rebuild one execution from durable request/result evidence.

        This helper never calls the solver gateway.  A running/unknown canonical episode is
        settled only from the immutable result wire persisted by ``PracticeEpisodeRunner``;
        absent that wire the caller must keep the episode quarantined.
        """
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        episode_id = episode_record.logical_id
        try:
            episode = PracticeEpisode.from_dict(episode_record.payload)
        except RSILearningError as exc:
            raise RSILearningError("rsi_episode_record_invalid") from exc
        saved = self.ledger.episode_result(episode_id)
        settled_failure = episode.status in {"failed", "timed_out", "abandoned", "cancelled"}
        journal = self.ledger.episode_reconciliation(episode_id) if settled_failure else ()
        reconciled_failure = bool(journal and journal[-1]["worker_state"] == episode.status)
        if saved is None:
            if reconciled_failure and request_hint is not None:
                # A diagnostic view of explicit terminal evidence, never a fabricated solver
                # receipt.  The absent/unknown immutable worker result remains unchanged.
                request = request_hint
                result = SolverResult(
                    episode_id, request.digest(), episode.status, None, None, None,
                    journal[-1]["journal_sha256"], terminal_reason=episode.terminal_reason or "reconciled_failure",
                )
            elif episode.status == "unknown":
                raise RSILearningError("rsi_unknown_reconcile_required")
            else:
                raise RSILearningError("rsi_resume_recovery_required")
        else:
            request, result = saved
            if result.status == "unknown" and reconciled_failure:
                result = replace(result, status=episode.status,
                                 terminal_reason=episode.terminal_reason or "reconciled_failure")
        if (
            request.episode_id != episode_id
            or episode.request_sha256 != request.digest()
            or result.episode_id != episode_id
            or result.request_sha256 != request.digest()
            or request.contract_sha256 != episode.contract_sha256
            or request.evaluator_sha256 != episode.evaluator_sha256
            or request.environment_sha256 != episode.environment_sha256
            or request.memory_snapshot_sha256 != episode.memory_snapshot_sha256
            or request.solver_id != episode.solver_id
        ):
            raise RSILearningError("rsi_episode_result_conflict")
        self._usage_replay_marker(episode, request)
        if result.status == "unknown":
            raise RSILearningError("rsi_unknown_reconcile_required")
        if episode.status in {"completed", "failed", "timed_out", "abandoned", "cancelled"} and result.status != episode.status:
            raise RSILearningError("rsi_episode_result_conflict")

        # A canonical running/unknown head is the only state that needs reconciliation.  If a
        # previous resume already settled it, simply read the terminal head and replay it.
        head = episode_record
        if episode.status in {"running", "unknown"}:
            result_sha256 = hashlib.sha256(canonical_json(result.to_dict())).hexdigest()
            evidence = {
                "reconciliation": {
                    "source": "persisted_solver_result",
                    "episode_id": episode_id,
                    "request_sha256": request.digest(),
                    "result_sha256": result_sha256,
                }
            }
            worker_state = result.status
            if worker_state not in {"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"}:
                raise RSILearningError("rsi_solver_status_invalid")
            head = self.ledger.reconcile_episode(
                episode_id,
                worker_state=worker_state,
                expected_record_sha256=head.record_sha256,
                result=result,
                evidence=evidence,
            )
            episode = PracticeEpisode.from_dict(head.payload)
        elif episode.status == "completed":
            # A completed head may have been written before the controller died while attaching
            # the verifier.  Attach it exactly once from the same immutable result.
            pass
        elif episode.status not in {"failed", "timed_out", "abandoned", "cancelled"}:
            raise RSILearningError("rsi_resume_checkpoint_unavailable")

        if result.status == "completed" and episode.status == "completed" and episode.verifier is None:
            decision = self._verify_episode(episode, request, result, before_verify)
            verified = episode.attach_verifier(decision)
            head = self.ledger.append_episode_record(verified, expected_record_sha256=head.record_sha256)
            episode = verified
        if episode.verifier is not None:
            decision = episode.verifier
        else:
            decision = self._verify_episode(episode, request, result, before_verify)
        return EpisodeExecution(episode, request, result, decision)

    def _usage_replay_marker(self, episode: PracticeEpisode, request: SolverRequest) -> None:
        PracticeEpisodeRunner.ensure_unknown_solver_usage(self.usage_ledger, episode, request)

    @staticmethod
    def _merge_resume_executions(
        record: RSIRecord,
        executions: Sequence[EpisodeExecution],
    ) -> tuple[tuple[EpisodeExecution, ...], tuple[EpisodeExecution, ...]]:
        targets: dict[str, EpisodeExecution] = {}
        practices: dict[str, EpisodeExecution] = {}
        for execution in executions:
            bucket = targets if execution.episode.episode_kind == "target" else practices
            bucket[execution.episode.episode_id] = execution
        def ordered(values: Mapping[str, EpisodeExecution]) -> tuple[EpisodeExecution, ...]:
            return tuple(sorted(values.values(), key=lambda item: (item.episode.wave, item.episode.ordinal, item.episode.episode_id)))
        # A terminal checkpoint is authoritative when it contains a full execution wire.  Durable
        # episode heads fill the gap left by a crash before the run checkpoint was advanced.
        try:
            for item in record.payload.get("target_attempts", []):
                execution = RSILearningController._deserialize_execution(item)
                targets.setdefault(execution.episode.episode_id, execution)
            for item in record.payload.get("practice_episodes", []):
                execution = RSILearningController._deserialize_execution(item)
                practices.setdefault(execution.episode.episode_id, execution)
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_resume_checkpoint_corrupt") from exc
        return ordered(targets), ordered(practices)

    def _save_flow(self, record: RSIRecord | None, state: dict[str, Any]) -> None:
        """Publish the whole recovery boundary before permitting the next side effect."""
        self._sync_curriculum_checkpoint(state)
        if self.ledger is None or record is None:
            return
        previous = self.ledger.controller_checkpoint(record.logical_id)
        if previous is not None:
            from .rsi_parent_budget import ParentRunBudget

            ParentRunBudget.synchronize(state, previous[1])
        if previous is not None and previous[1] == state:
            return
        self.ledger.write_controller_checkpoint(
            record.logical_id, state, expected_sha256=previous[0] if previous else None,
        )

    def _flow_state(self, record: RSIRecord | None, *, run_id: str, plan: dict[str, Any],
                    pins: dict[str, str], budget: Mapping[str, Any]) -> dict[str, Any]:
        if record is not None:
            self._restore_failure_curriculum(record.payload)
        state = {
            "schema_version": "2", "kind": "rsi_run_checkpoint", "run_id": run_id,
            "callback_protocol_version": "1",
            "mode": plan["mode"], "plan": plan, "pins": pins, "status": "running",
            "phase": "created", "current_episode_id": None,
            "root_snapshot": self.snapshot.to_dict(), "memory_snapshot": self.snapshot.to_dict(),
            "budget_state": (record.payload["budget_state"] if record is not None
                             else RSIRunBudget.create(budget).to_dict()), "intents": {},
            "executions": {}, "decisions": {}, "judgments": {},
        }
        self._sync_curriculum_checkpoint(state)
        return state

    @staticmethod
    def _decision_from_dict(value: Mapping[str, Any]) -> CurriculumDecision:
        clean = dict(value)
        clean["compatible_solvers"] = tuple(clean["compatible_solvers"])
        return CurriculumDecision(**clean)

    def _flow_result(self, state: Mapping[str, Any]) -> LearningRunResult:
        executions = [self._deserialize_execution(item) for item in state["executions"].values()]
        executions.sort(key=lambda item: (item.episode.wave, item.episode.ordinal, item.episode.episode_id))
        return LearningRunResult(
            state["run_id"], state["status"], MemorySnapshot.from_dict(state["memory_snapshot"]),
            tuple(item for item in executions if item.episode.episode_kind == "target"),
            tuple(item for item in executions if item.episode.episode_kind == "practice"),
            checkpoint_episode_id=state.get("current_episode_id"),
        )

    def _finish_flow(self, record: RSIRecord | None, state: dict[str, Any], status: str) -> LearningRunResult:
        state.update(status=status, phase="terminal")
        self._save_flow(record, state)
        result = self._flow_result(state)
        if record is not None and self.ledger is not None:
            latest = self.ledger.get_run(record.logical_id)
            if latest is not None and latest.state not in {"completed", "failed", "cancelled", "budget_exhausted"}:
                self._finish_run(latest, result, budget_state=state["budget_state"])
        return result

    def _prepare_intent(self, record: RSIRecord | None, state: dict[str, Any],
                        episode: PracticeEpisode, request: SolverRequest) -> None:
        key = episode.episode_id
        expected = {"episode": episode.to_record_dict(), "request": request.to_dict()}
        if key in state["intents"]:
            if state["intents"][key] != expected:
                raise RSILearningError("rsi_resume_episode_drift")
            return
        self._check_memory_admission(request, parent_run_id=state["run_id"])
        if self.ledger is not None:
            persisted = self.ledger.controller_checkpoint(state["run_id"])
            if persisted is not None:
                from .rsi_parent_budget import ParentRunBudget

                ParentRunBudget.synchronize(state, persisted[1])
        budget = RSIRunBudget.load(state["budget_state"])
        self._reserve_episode_budget(budget, episode_kind=episode.episode_kind, depth=0, ancestry=(key,))
        state["budget_state"] = budget.to_dict()
        state["intents"][key] = expected
        state.update(phase="launch", current_episode_id=key)
        self._save_flow(record, state)

    def _execute_intent(self, state: Mapping[str, Any], episode_id: str) -> EpisodeExecution:
        intent = state["intents"][episode_id]
        episode = PracticeEpisode.from_dict(intent["episode"])
        request = SolverRequest.from_dict(intent["request"])
        if self.ledger is not None:
            head = self.ledger.get_episode(episode_id)
            if head is not None:
                if head.request_sha256 != request.digest():
                    raise RSILearningError("rsi_resume_episode_drift")
                return self._resume_episode_execution(
                    head, request_hint=request,
                    before_verify=RSIRunBudget.load(state["budget_state"]).check,
                )
        # The running episode is persisted by the runner before invoking the gateway.  Therefore
        # only an intent with no episode head proves that the solver has not been invoked yet.
        budget = RSIRunBudget.load(state["budget_state"])
        budget.check()
        controller = self

        class ControllerVerifier:
            def verify(self, episode, request, result):
                return controller._verify_episode(episode, request, result, budget.check)

        def before_run() -> None:
            self._check_memory_admission(request, parent_run_id=state["run_id"])
            # Governance reads may wait for a SQLite reader. Recheck the same absolute
            # deadline immediately afterwards before persisting running or dispatching.
            budget.check()

        return PracticeEpisodeRunner(
            self.gateway, ControllerVerifier(), self.ledger, self.usage_ledger,
            before_run=before_run,
        ).run(episode, request)

    def _flow_episode(self, record: RSIRecord | None, state: dict[str, Any],
                      episode: PracticeEpisode, request: SolverRequest) -> EpisodeExecution:
        key = episode.episode_id
        if key in state["executions"]:
            return self._deserialize_execution(state["executions"][key])
        self._prepare_intent(record, state, episode, request)
        execution = self._execute_intent(state, key)
        state["executions"][key] = self._serialize_execution(execution)
        state.update(phase="evaluated", current_episode_id=key)
        self._save_flow(record, state)
        return execution

    def _commit_flow(self, record: RSIRecord | None, state: dict[str, Any], execution: EpisodeExecution,
                     decision: CurriculumDecision, *, frozen_parent: str | None = None) -> None:
        if not execution.passed:
            return
        if self.generation_regression_tasks:
            self._commit_governed_flow(record, state, execution, decision, frozen_parent=frozen_parent)
            return
        memory_id = f"memory-{execution.episode.episode_id}"
        if any(item.memory_id == memory_id for item in self.snapshot.items):
            return
        RSIRunBudget.load(state["budget_state"]).check()
        state.update(phase="commit", current_episode_id=execution.episode.episode_id)
        self._save_flow(record, state)
        self._commit(execution, decision, expected_episode_snapshot_sha256=frozen_parent,
                     source_snapshot_sha256=frozen_parent)
        state["memory_snapshot"] = self.snapshot.to_dict()
        state["phase"] = "committed"
        self._save_flow(record, state)

    def _commit_governed_flow(self, record: RSIRecord | None, state: dict[str, Any],
                              execution: EpisodeExecution, decision: CurriculumDecision,
                              *, frozen_parent: str | None) -> None:
        """Keep immutable candidate publication separate from effective memory admission."""
        key = execution.episode.episode_id
        generations = state.setdefault("generations", {})
        entry = generations.get(key)
        completed = entry is not None and entry.get("status") in {"active", "rejected"}
        if entry is None:
            RSIRunBudget.load(state["budget_state"]).check()
            state.update(phase="commit", current_episode_id=key)
            self._save_flow(record, state)
            parent = self.snapshot
            try:
                candidate = self._commit(execution, decision, expected_episode_snapshot_sha256=frozen_parent,
                                         source_snapshot_sha256=frozen_parent)
            finally:
                self.memory_store = RSIMemoryStore(parent)
            entry = {"generation_id": "controller-generation:" + _record_digest({"run": state["run_id"], "episode": key}),
                     "parent_memory": parent.to_dict(), "candidate_memory": candidate.to_dict(), "status": "pending",
                     "admission_checkpoint_sha256": None}
            generations[key] = entry
            self._save_flow(record, state)
        else:
            try:
                parent = MemorySnapshot.from_dict(entry["parent_memory"])
                candidate = MemorySnapshot.from_dict(entry["candidate_memory"])
                expected = MemorySnapshot(
                    f"snapshot-memory-{key}", parent.digest(), parent.items + (self._memory_item(execution, decision),),
                )
                persisted = self.ledger.get("memory:" + candidate.snapshot_id)
                if (set(entry) != {"generation_id", "parent_memory", "candidate_memory", "status", "admission_checkpoint_sha256"}
                        or entry["generation_id"] != "controller-generation:" + _record_digest({"run": state["run_id"], "episode": key})
                        or candidate != expected or persisted is None or persisted.payload != candidate.to_dict()
                        or entry["status"] not in {"pending", "active", "rejected"}):
                    raise ValueError("generation drift")
            except (KeyError, TypeError, ValueError) as exc:
                raise RSILearningError("rsi_generation_controller_checkpoint_corrupt") from exc
        if completed:
            try:
                self._generation_admission_checkpoint(entry, execution)
            except (KeyError, TypeError, ValueError) as exc:
                raise RSILearningError("rsi_generation_controller_checkpoint_corrupt") from exc
            return
        result = self.memory_admission_gate.admit_generation(
            entry["generation_id"], candidate, parent,
            {f"memory-{key}": execution.verifier}, self.generation_campaign_runner(state["run_id"]),
        )
        if result.status not in {"active", "rejected"}:
            self.memory_store = RSIMemoryStore(parent)
            state.update(memory_snapshot=parent.to_dict(), phase="generation_pending")
            self._save_flow(record, state)
            raise RSILearningError("rsi_generation_reconcile_required")
        self.memory_store = RSIMemoryStore(result.effective_snapshot)
        entry["status"] = result.status
        entry["admission_checkpoint_sha256"] = self.memory_admission_gate.inspect(entry["generation_id"])[0]
        state.update(memory_snapshot=self.snapshot.to_dict(), phase="committed")
        self._save_flow(record, state)

    @staticmethod
    def _uncertain_status(execution: EpisodeExecution) -> str | None:
        if execution.result.status == "unknown":
            return "unknown"
        if execution.result.status in {"timed_out", "abandoned", "cancelled"}:
            return "failed"
        return None

    def _drive_drs(self, record: RSIRecord | None, state: dict[str, Any]) -> LearningRunResult:
        plan, pins, run_id = state["plan"], state["pins"], state["run_id"]
        for attempt in range(plan["max_target_attempts"]):
            target_id = f"{run_id}-target-{attempt}"
            if target_id in state["intents"]:
                target = PracticeEpisode.from_dict(state["intents"][target_id]["episode"])
                request = SolverRequest.from_dict(state["intents"][target_id]["request"])
            else:
                target = self._target_episode(run_id, target_id, pins, attempt)
                request = self._request(target, budget=state["budget_state"]["planned"])
            execution = self._flow_episode(record, state, target, request)
            uncertain = self._uncertain_status(execution)
            if uncertain:
                return self._finish_flow(record, state, uncertain)
            if target_id not in state["judgments"]:
                def judge(execution=execution) -> dict[str, Any]:
                    accepted, diagnosis = self.target_judge(execution)
                    if type(accepted) is not bool:
                        raise RSILearningError("rsi_callback_result_invalid")
                    return {"accepted": accepted and execution.passed, "diagnosis": diagnosis}

                judgment = self._invoke_callback(
                    run_id, f"judge:{target_id}", "judge", {"execution": self._serialize_execution(execution)},
                    judge, RSIRunBudget.load(state["budget_state"]).check,
                )
                state["judgments"][target_id] = [judgment["accepted"], judgment["diagnosis"]]
                self._save_flow(record, state)
            accepted, diagnosis = state["judgments"][target_id]
            if accepted:
                return self._finish_flow(record, state, "completed")
            if attempt >= plan["max_practice_rounds"]:
                break
            practice_id = f"{run_id}-practice-{attempt}-0"
            if practice_id not in state["decisions"]:
                def choose_curriculum(execution=execution, diagnosis=diagnosis, attempt=attempt) -> dict[str, Any]:
                    decision = self.curriculum.choose(
                        target=execution.episode, diagnosis=diagnosis, wave=attempt, ordinal=0,
                    )
                    # Persist the mutable selection ledger while the callback journal is still
                    # open.  A crash after callback completion but before ``decisions`` is
                    # published can then replay the completed callback without charging a second
                    # curriculum selection or budget unit.
                    self._sync_curriculum_checkpoint(state)
                    self._save_flow(record, state)
                    return decision.to_dict()

                state["decisions"][practice_id] = self._invoke_callback(
                    run_id, f"curriculum:{practice_id}", "curriculum",
                    {"target": execution.episode.to_record_dict(), "diagnosis": diagnosis, "wave": attempt, "ordinal": 0},
                    choose_curriculum,
                    RSIRunBudget.load(state["budget_state"]).check,
                )
                self._save_flow(record, state)
            decision = self._decision_from_dict(state["decisions"][practice_id])
            if practice_id in state["intents"]:
                practice_episode = PracticeEpisode.from_dict(state["intents"][practice_id]["episode"])
                practice_request = SolverRequest.from_dict(state["intents"][practice_id]["request"])
            else:
                practice_episode = PracticeEpisode(
                    practice_id, run_id, target.contract_sha256, target.evaluator_sha256,
                    target.environment_sha256, self.snapshot.digest(), target.solver_id, "planned",
                    episode_kind="practice", wave=attempt, ordinal=0, parent_target_episode_id=target_id,
                )
                practice_request = self._request(
                    practice_episode, budget=state["budget_state"]["planned"],
                    charter={**decision.to_dict(), "decision_sha256": decision.digest()},
                )
            practice = self._flow_episode(record, state, practice_episode, practice_request)
            uncertain = self._uncertain_status(practice)
            if uncertain:
                return self._finish_flow(record, state, uncertain)
            self._commit_flow(record, state, practice, decision)
        return self._finish_flow(record, state, "failed")

    def _drive_brs(self, record: RSIRecord | None, state: dict[str, Any]) -> LearningRunResult:
        plan, pins, run_id = state["plan"], state["pins"], state["run_id"]
        decisions = [self._decision_from_dict(item) for item in plan["practices"]]
        parent = MemorySnapshot.from_dict(state["root_snapshot"]).digest()
        episode_ids = []
        # Reserve and persist the whole wave before any child starts.  A partial reservation
        # failure terminates without launching; a crash resumes the same already-reserved IDs.
        for ordinal, decision in enumerate(decisions):
            key = f"{run_id}-practice-{plan['wave']}-{ordinal}"
            episode_ids.append(key)
            episode = PracticeEpisode(
                key, run_id, pins["contract_sha256"], pins["evaluator_sha256"],
                pins["environment_sha256"], parent, pins["solver_id"], "planned",
                episode_kind="practice", wave=plan["wave"], ordinal=ordinal,
                parent_target_episode_id=f"{run_id}-target-seed",
            )
            request = self._request(episode, budget=state["budget_state"]["planned"],
                                    charter={**decision.to_dict(), "decision_sha256": decision.digest()})
            self._prepare_intent(record, state, episode, request)
        pending = [key for key in episode_ids if key not in state["executions"]]
        # All controller writes remain in the owning thread.  Workers persist only their own
        # episode/result evidence and never mutate this journal or the frozen memory parent.
        if pending:
            with ThreadPoolExecutor(max_workers=plan.get("max_workers") or len(pending)) as pool:
                futures = {key: pool.submit(self._execute_intent, state, key) for key in pending}
                for key in pending:
                    execution = futures[key].result()
                    if execution.episode.memory_snapshot_sha256 != parent:
                        raise RSILearningError("rsi_brs_snapshot_changed")
                    state["executions"][key] = self._serialize_execution(execution)
                    state.update(phase="evaluated", current_episode_id=key)
                    self._save_flow(record, state)
        results = [self._deserialize_execution(state["executions"][key]) for key in episode_ids]
        uncertain = [self._uncertain_status(item) for item in results]
        if any(uncertain):
            return self._finish_flow(record, state, "unknown" if "unknown" in uncertain else "failed")
        for execution, decision in zip(results, decisions):
            self._commit_flow(record, state, execution, decision, frozen_parent=parent)
        return self._finish_flow(record, state, "completed")

    def _drive(self, record: RSIRecord | None, state: dict[str, Any], *, now: object | None = None) -> LearningRunResult:
        try:
            if state["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
                return self._finish_flow(record, state, state["status"])
            RSIRunBudget.load(state["budget_state"]).check(now=now)
            return self._drive_drs(record, state) if state["mode"] == "drs" else self._drive_brs(record, state)
        except RSILearningError as exc:
            if str(exc) != "rsi_budget_exhausted":
                raise
            return self._finish_flow(record, state, "budget_exhausted")

    def _validate_resume_identity(self, record: RSIRecord, observed: Mapping[str, Any] | None,
                                  budget_policy: Mapping[str, Any] | None) -> None:
        payload = record.payload
        expected = {**payload, **dict(payload.get("fingerprints", {}))}
        if budget_policy is not None and dict(budget_policy) != payload.get("budget", {}):
            raise RSILearningError("rsi_resume_budget_drift")
        for key, value in (observed or {}).items():
            values = value.items() if key == "fingerprints" and isinstance(value, Mapping) else [(key, value)]
            for field, actual in values:
                if field in expected and expected[field] != actual:
                    raise RSILearningError(f"rsi_resume_{field}_drift")
        stored = payload.get("fingerprints", {}).get("run_fingerprint")
        if isinstance(stored, Mapping):
            # Caller-supplied old fingerprints are assertions, never a substitute for computing
            # the current gateway/verifier/curriculum/judge identity on this process.
            actual, _ = self._run_fingerprint(
                contract_sha256=payload["contract_sha256"], evaluator_sha256=payload["evaluator_sha256"],
                environment_sha256=payload["environment_sha256"], solver_id=payload["solver_id"],
                memory_snapshot_sha256=stored["memory_snapshot_sha256"],
            )
            try:
                ensure_fingerprint_compatible(RSIFingerprintContract.from_dict(stored), actual)
            except ValueError as exc:
                raise RSILearningError("rsi_resume_fingerprint_drift") from exc

    def resume(self, run_id: str, *, now: object | None = None,
               observed_fingerprints: Mapping[str, Any] | None = None,
               budget_policy: Mapping[str, Any] | None = None) -> LearningRunResult:
        _id(run_id, "run_id")
        if self.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        with self.ledger.controller_lock(run_id):
            return self._resume_locked(run_id, now=now, observed_fingerprints=observed_fingerprints,
                                       budget_policy=budget_policy)

    def _resume_locked(self, run_id: str, *, now: object | None = None,
                       observed_fingerprints: Mapping[str, Any] | None = None,
                       budget_policy: Mapping[str, Any] | None = None) -> LearningRunResult:
        record = self.ledger.get_run(run_id)
        if record is None:
            raise RSILearningError("rsi_run_missing")
        if record.state == "unknown" and not self.ledger.episode_ids_for_run(run_id):
            raise RSILearningError("rsi_unknown_reconcile_required")
        self._validate_resume_identity(record, observed_fingerprints, budget_policy)
        if record.state in {"completed", "failed", "cancelled", "budget_exhausted"}:
            checkpoint = self.ledger.controller_checkpoint(run_id)
            if checkpoint and checkpoint[1].get("schema_version") == "2":
                self._check_budget_history(record)
            terminal_executions = checkpoint[1].get("executions", {}).values() if checkpoint else ()
            if not terminal_executions:
                terminal_executions = (
                    *record.payload.get("target_attempts", ()),
                    *record.payload.get("practice_episodes", ()),
                )
            for raw_execution in terminal_executions:
                execution = self._deserialize_execution(raw_execution)
                self._usage_replay_marker(execution.episode, execution.request)
            self._restore_failure_curriculum(checkpoint[1] if checkpoint else record.payload)
            return LearningRunResult(
                run_id, record.state, MemorySnapshot.from_dict(record.payload["memory_snapshot"]),
                tuple(self._deserialize_execution(item) for item in record.payload.get("target_attempts", [])),
                tuple(self._deserialize_execution(item) for item in record.payload.get("practice_episodes", [])),
                checkpoint_episode_id=record.payload.get("current_episode_id"),
            )
        checkpoint = self.ledger.controller_checkpoint(run_id)
        state = checkpoint[1] if checkpoint else None
        if state is None and record.payload.get("plan") is not None:
            if self.ledger.episode_ids_for_run(run_id):
                raise RSILearningError("rsi_resume_checkpoint_corrupt")
            # The run request is persisted before the first controller journal.  With no
            # episode heads no launch has happened; retain its original budget and snapshot.
            self.memory_store = RSIMemoryStore(MemorySnapshot.from_dict(record.payload["memory_snapshot"]))
            state = self._flow_state(
                record, run_id=run_id, plan=record.payload["plan"],
                pins={key: record.payload[key] for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id",
                )}, budget=record.payload["budget"],
            )
            self._save_flow(record, state)
        if state is None or state.get("schema_version") != "2":
            # Pre-journal records do not contain a complete launch plan.  Reconcile evidence but
            # never guess a missing BRS wave or issue new solver calls from a legacy checkpoint.
            heads = [self.ledger.get_episode(key) for key in self.ledger.episode_ids_for_run(run_id)]
            if record.payload.get("callback_protocol_version") != "1":
                for head in heads:
                    saved = self.ledger.episode_result(head.logical_id)
                    if (head.payload.get("verifier") is None and saved is not None
                            and saved[1].status == "completed"):
                        raise RSILearningError("rsi_callback_migration_required")
            executions = [self._resume_episode_execution(head) for head in heads]
            targets, practices = self._merge_resume_executions(record, executions)
            return LearningRunResult(
                run_id, record.state, MemorySnapshot.from_dict(record.payload["memory_snapshot"])
                if "memory_snapshot" in record.payload else self.snapshot, targets, practices,
                checkpoint_episode_id=record.payload.get("current_episode_id"),
            )
        if (state["run_id"] != run_id or state["plan"] != record.payload.get("plan")
                or state["pins"] != {key: record.payload[key] for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id",
                )}):
            raise RSILearningError("rsi_resume_checkpoint_corrupt")
        RSIRunBudget.load(state["budget_state"]).assert_matches(record.payload["budget"])
        self._check_budget_history(record)
        root = MemorySnapshot.from_dict(state["root_snapshot"])
        if root.digest() != record.payload["fingerprints"]["memory_snapshot_sha256"]:
            raise RSILearningError("rsi_resume_memory_drift")
        self.memory_store = RSIMemoryStore(MemorySnapshot.from_dict(state["memory_snapshot"]))
        self._restore_failure_curriculum(state)
        if state["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
            return self._finish_flow(record, state, state["status"])
        if state.get("callback_protocol_version") != "1":
            if (record.payload.get("callback_protocol_version") is not None
                    or self.ledger.episode_ids_for_run(run_id)):
                raise RSILearningError("rsi_callback_migration_required")
            # An older run with no episode head has never reached a solver or callback.
            state["callback_protocol_version"] = "1"
            self._save_flow(record, state)
        self._check_callback_quarantine(state)
        # Quarantine the entire run before verifying, merging, or launching any other child.
        heads = [self.ledger.get_episode(key) for key in self.ledger.episode_ids_for_run(run_id)]
        for head in heads:
            if head.state in {"running", "unknown"}:
                saved = self.ledger.episode_result(head.logical_id)
                if saved is None or saved[1].status == "unknown":
                    raise RSILearningError("rsi_unknown_reconcile_required" if head.state == "unknown"
                                           else "rsi_resume_recovery_required")
            if head.logical_id not in state["intents"]:
                raise RSILearningError("rsi_resume_episode_drift")
        try:
            run_budget = RSIRunBudget.load(state["budget_state"])
            run_budget.check(now=now)
            if (record.state == "unknown"
                    and state.get("reconcile_attempt_record_sha256") != record.record_sha256):
                run_budget.reserve_unknown_reconcile()
                state["budget_state"] = run_budget.to_dict()
                state["reconcile_attempt_record_sha256"] = record.record_sha256
                self._save_flow(record, state)
            for head in heads:
                cached = state["executions"].get(head.logical_id)
                if cached is not None and cached["episode"] == head.payload:
                    continue
                execution = self._resume_episode_execution(
                    head, request_hint=SolverRequest.from_dict(state["intents"][head.logical_id]["request"]),
                    before_verify=run_budget.check,
                )
                state["executions"][head.logical_id] = self._serialize_execution(execution)
                self._save_flow(record, state)
            if record.state == "unknown":
                record = self.ledger.reconcile_run(
                    run_id, expected_record_sha256=record.record_sha256,
                    evidence={"reconciliation": {"source": "controller_episode_evidence"}},
                )
            elif record.state in {"created", "paused"}:
                record = self.ledger.transition(run_id, state="running", expected_record_sha256=record.record_sha256)
            if state["status"] == "unknown":
                state["status"] = "running"
            self._save_flow(record, state)
            return self._drive(record, state, now=now)
        except RSILearningError as exc:
            if str(exc) != "rsi_budget_exhausted":
                raise
            return self._finish_flow(record, state, "budget_exhausted")

    @staticmethod
    def _reserve_episode_budget(
        run_budget: RSIRunBudget | None,
        *,
        episode_kind: str,
        depth: int,
        ancestry: tuple[str, ...],
    ) -> None:
        """Charge one launch and the evaluator/verifier stages as one atomic budget gate."""

        if run_budget is not None:
            run_budget.reserve_launch_with_stages(
                episode_kind=episode_kind,
                depth=depth,
                ancestry=ancestry,
                stages=("evaluator", "verifier"),
            )

    def _finish_run(
        self,
        record: RSIRecord | None,
        result: LearningRunResult,
        *,
        budget_state: Mapping[str, Any] | None = None,
    ) -> None:
        if self.ledger is None or record is None:
            return
        self.ledger.transition(
            result.run_id,
            state=result.status,
            expected_record_sha256=record.record_sha256,
            payload_patch={
                "target_attempt_count": len(result.target_attempts),
                "practice_episode_count": len(result.practice_episodes),
                "memory_snapshot_sha256": result.memory_snapshot.digest(),
                "transfer_status": result.transfer.status if result.transfer is not None else None,
                "phase": "terminal",
                "current_episode_id": result.current_episode_id,
                "target_attempts": [self._serialize_execution(item) for item in result.target_attempts],
                "practice_episodes": [self._serialize_execution(item) for item in result.practice_episodes],
                "memory_snapshot": result.memory_snapshot.to_dict(),
                **({"budget_state": dict(budget_state)} if budget_state is not None else {}),
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

    def _check_memory_admission(self, request: SolverRequest, *, parent_run_id: str | None = None) -> None:
        if self.memory_admission_gate is None:
            return
        snapshot = self.snapshot
        if request.memory_snapshot_sha256 != snapshot.digest():
            raise RSILearningError("rsi_memory_snapshot_gate_request_drift")
        if parent_run_id is not None and self.ledger is not None:
            parent = self.ledger.get_run(parent_run_id)
            if parent is None:
                raise RSILearningError("rsi_parent_budget_missing")
            self._validate_resume_identity(parent, None, None)
        if self.generation_revalidate_before_dispatch and snapshot.items:
            if parent_run_id is None or self.ledger is None:
                raise RSILearningError("rsi_generation_controller_config_invalid")
            gate = self.memory_admission_gate
            generation_id = gate._snapshot_generation(snapshot)
            checkpoint = gate.inspect(generation_id)
            if checkpoint is None:
                raise RSILearningError("rsi_generation_controller_admission_drift")
            validation_id = "dispatch:" + request.digest()
            state = checkpoint[1]
            known = state["validations"].get(validation_id)
            if state["phase"] == "quarantined":
                raise RSILearningError("rsi_generation_revalidation_rejected")
            if state["phase"] == "revalidating" and (
                state["pending_validation"] != validation_id or known is None
                or known["status"] == "started"
                or not self.ledger.controller_lock_held(parent_run_id)
            ):
                raise RSILearningError("rsi_generation_revalidation_reconcile_required")
            if known is not None and known["status"] == "completed" and state["phase"] == "active":
                # BRS dispatch workers cannot acquire the parent lock held by their controller.
                # Completed validation replay is read-only and checks live configuration again.
                from .rsi_generation_campaign import GenerationCampaignRunner

                config = self._generation_campaign_config_readonly(parent_run_id)
                if (known["runner_fingerprint"] != component_fingerprint(GenerationCampaignRunner, config=config)
                        or known["runner_parent"] != config["parent"] or known["runner_manifest"] != config["manifest"]):
                    raise RSILearningError("rsi_generation_controller_admission_drift")
                report = gate.deserialize_report(known["report"])
                if not report.promotion_eligible:
                    raise RSILearningError("rsi_generation_revalidation_rejected")
            else:
                result = gate.revalidate_generation(
                    generation_id, validation_id, self.generation_campaign_runner(parent_run_id),
                )
                if result.status in {"rejected", "quarantined"}:
                    raise RSILearningError("rsi_generation_revalidation_rejected")
                if result.status != "active":
                    raise RSILearningError("rsi_generation_revalidation_reconcile_required")
                if result.effective_snapshot != snapshot:
                    raise RSILearningError("rsi_generation_controller_admission_drift")
        self.memory_admission_gate.validate(snapshot)

    def _practice(self, *, run_id: str, target: PracticeEpisode, decision: CurriculumDecision, wave: int, ordinal: int) -> EpisodeExecution:
        episode = PracticeEpisode(
            f"{run_id}-practice-{wave}-{ordinal}", run_id, target.contract_sha256, target.evaluator_sha256,
            target.environment_sha256, self.snapshot.digest(), target.solver_id, "planned",
            episode_kind="practice", wave=wave, ordinal=ordinal, parent_target_episode_id=target.episode_id,
        )
        request = self._request(episode, charter={**decision.to_dict(), "decision_sha256": decision.digest()})
        return PracticeEpisodeRunner(
            self.gateway, self.verifier, self.ledger, self.usage_ledger,
            before_run=lambda: self._check_memory_admission(request, parent_run_id=episode.run_id),
        ).run(episode, request)

    @staticmethod
    def _memory_item(execution: EpisodeExecution, decision: CurriculumDecision) -> MemoryItem:
        return MemoryItem(
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
        memory = self._memory_item(execution, decision)
        if self.ledger is not None:
            existing = self.ledger.get(f"memory:snapshot-{memory.memory_id}")
            if existing is not None:
                expected = MemorySnapshot(
                    f"snapshot-{memory.memory_id}", self.snapshot.digest(), self.snapshot.items + (memory,),
                )
                if existing.kind != "memory" or existing.payload != expected.to_dict():
                    raise RSILearningError("rsi_memory_snapshot_conflict")
                # Publication may have completed just before the controller checkpoint crashed.
                # Reopen that exact snapshot rather than committing the same memory twice.
                self.memory_store = RSIMemoryStore(expected)
                return expected
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

    def _run_plan(self, *, run_id: str, pins: dict[str, str], plan: dict[str, Any],
                  budget: Mapping[str, Any]) -> LearningRunResult:
        _id(run_id, "run_id")
        _id(pins["solver_id"], "solver_id")
        for key in ("contract_sha256", "evaluator_sha256", "environment_sha256"):
            _digest(pins[key], key)
        # Hold the same lock for both fresh runs and recovery, including while workers execute.
        # A second process must never mistake a live worker for a resumable crashed controller.
        guard = self.ledger.controller_lock(run_id) if self.ledger is not None else nullcontext()
        with guard:
            if self.ledger is not None:
                prior = self.ledger.get_run(run_id)
                if prior is not None:
                    self._assert_existing_run_request(prior, mode=plan["mode"], budget=budget, **pins)
                    if prior.payload.get("plan") != plan:
                        raise RSILearningError("rsi_resume_plan_drift")
                    return self._resume_locked(run_id)
            record = self._start_run(run_id=run_id, mode=plan["mode"], budget=budget, plan=plan, **pins)
            state = self._flow_state(record, run_id=run_id, plan=plan, pins=pins, budget=budget)
            self._save_flow(record, state)
            return self._drive(record, state)

    def run_drs(self, *, run_id: str, contract_sha256: str, evaluator_sha256: str,
                environment_sha256: str, solver_id: str, max_practice_rounds: int = 3,
                max_target_attempts: int = 4, budget: Mapping[str, Any] | None = None) -> LearningRunResult:
        if (type(max_practice_rounds) is not int or max_practice_rounds < 0
                or type(max_target_attempts) is not int or max_target_attempts < 1):
            raise RSILearningError("rsi_learning_budget_invalid")
        pins = {"contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256, "solver_id": solver_id}
        policy = dict(budget or {})
        policy.setdefault("max_practice_rounds", max_practice_rounds)
        policy.setdefault("max_target_attempts", max_target_attempts)
        plan = {"mode": "drs", "max_practice_rounds": max_practice_rounds,
                "max_target_attempts": max_target_attempts}
        return self._run_plan(run_id=run_id, pins=pins, plan=plan, budget=policy)

    def run_brs(self, *, run_id: str, contract_sha256: str, evaluator_sha256: str,
                environment_sha256: str, solver_id: str, practices: Sequence[CurriculumDecision],
                wave: int = 0, budget: Mapping[str, Any] | None = None,
                max_workers: int | None = None) -> LearningRunResult:
        if type(wave) is not int or wave < 0 or (max_workers is not None
                                                and (type(max_workers) is not int or max_workers < 1)):
            raise RSILearningError("rsi_learning_budget_invalid")
        pins = {"contract_sha256": contract_sha256, "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256, "solver_id": solver_id}
        policy = dict(budget or {})
        policy.setdefault("max_practice_rounds", len(practices))
        policy.setdefault("max_target_attempts", 1)
        plan = {"mode": "brs", "practices": [item.to_dict() for item in practices],
                "wave": wave, "max_workers": max_workers}
        return self._run_plan(run_id=run_id, pins=pins, plan=plan, budget=policy)



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
