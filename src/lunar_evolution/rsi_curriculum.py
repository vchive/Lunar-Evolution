"""Finite, deterministic RSI practice selection without providers or execution side effects."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_controller import CurriculumDecision, EpisodeExecution
from .rsi_learning import PracticeEpisode, RSILearningError

_POLICY_VERSION = "lunar-rsi-diversity-failure-boundary-v1"
_MAX_CANDIDATES = 256
_MAX_HISTORY = 256


def _fail(code: str) -> None:
    raise RSILearningError(f"rsi_curriculum_{code}")


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(c in value for c in "\x00\r\n"):
        _fail(f"{name}_invalid")
    try:
        if len(value.encode("utf-8")) > 256:
            _fail(f"{name}_invalid")
    except UnicodeEncodeError:
        _fail(f"{name}_invalid")
    return value


def _hash(value: object) -> str:
    try:
        return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RSILearningError("rsi_curriculum_record_invalid") from exc


def _bounded_items(value: Iterable[Any], maximum: int, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, Mapping)):
        _fail(f"{name}_invalid")
    result = []
    try:
        for item in value:
            result.append(item)
            if len(result) > maximum:
                _fail(f"{name}_too_large")
    except TypeError as exc:
        raise RSILearningError(f"rsi_curriculum_{name}_invalid") from exc
    return tuple(result)


@dataclass(frozen=True)
class CurriculumCandidate:
    """An explicit practice task; source paths and runtime commands are never inferred."""

    candidate_id: str
    practice_family: str
    capability_gap: str
    strategy: str
    expected_result: str
    failure_boundary: str
    compatible_solvers: tuple[str, ...]
    priority: int = 0

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        if type(self.priority) is not int or not 0 <= self.priority <= 1000:
            _fail("priority_invalid")
        # Reuse the existing charter validation; canonicalize solver ordering for deduplication.
        self.decision()
        if len(set(self.compatible_solvers)) != len(self.compatible_solvers):
            _fail("solvers_invalid")
        object.__setattr__(self, "compatible_solvers", tuple(sorted(self.compatible_solvers)))

    def decision(self, reason_code: str = "declared_practice") -> CurriculumDecision:
        return CurriculumDecision(
            self.practice_family, self.capability_gap, reason_code, self.strategy,
            self.expected_result, self.failure_boundary, self.compatible_solvers,
        )

    def semantic_digest(self) -> str:
        return self.decision().digest()

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "priority": self.priority, **self.decision().to_dict()}


@dataclass(frozen=True)
class CurriculumObservation:
    """One durable practice episode bound to its selected decision and declared candidate.

    Construct with ``from_execution`` at the execution boundary. On reload, the caller supplies
    the decision and episode reopened from its ledger. Receipt authentication remains the
    independent verifier's job; this policy never upgrades a status or raw solver score.
    """

    candidate_id: str
    decision: CurriculumDecision
    episode: PracticeEpisode

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        if not isinstance(self.decision, CurriculumDecision) or not isinstance(self.episode, PracticeEpisode):
            _fail("observation_invalid")
        self.episode.to_record_dict()
        if self.episode.episode_kind != "practice":
            _fail("observation_not_practice")
        if self.episode.solver_id not in self.decision.compatible_solvers:
            _fail("observation_solver_mismatch")

    @classmethod
    def from_execution(
        cls, candidate_id: str, decision: CurriculumDecision, execution: EpisodeExecution,
    ) -> CurriculumObservation:
        episode, request, result = execution.episode, execution.request, execution.result
        if (
            episode.request_sha256 != request.digest()
            or result.request_sha256 != request.digest()
            or result.episode_id != episode.episode_id
            or request.episode_id != episode.episode_id
            or result.status != episode.status
            or dict(request.practice_charter) != {**decision.to_dict(), "decision_sha256": decision.digest()}
        ):
            _fail("observation_execution_mismatch")
        for name in (
            "contract_sha256", "evaluator_sha256", "environment_sha256",
            "memory_snapshot_sha256", "solver_id",
        ):
            if getattr(request, name) != getattr(episode, name):
                _fail("observation_execution_mismatch")
        if episode.status == "completed" and episode.verifier != execution.verifier:
            _fail("observation_verifier_mismatch")
        return cls(candidate_id, decision, episode)

    @property
    def verified_outcome(self) -> str | None:
        episode, verifier = self.episode, self.episode.verifier
        if episode.status != "completed" or verifier is None or not verifier.independent_of_actor:
            return None
        for name in (
            "contract_sha256", "evaluator_sha256", "environment_sha256",
            "candidate_receipt_sha256", "execution_receipt_sha256",
            "official_evaluation_receipt_sha256",
        ):
            if getattr(verifier, name) is None or getattr(verifier, name) != getattr(episode, name):
                return None
        official = [check for check in verifier.checks if check.name == "official_evaluator"]
        if len(official) != 1 or official[0].receipt_sha256 != episode.official_evaluation_receipt_sha256:
            return None
        if verifier.outcome == "pass" and all(check.outcome == "pass" for check in verifier.checks):
            return "pass"
        if verifier.outcome == "fail" and any(check.outcome == "fail" for check in verifier.checks):
            return "fail"
        return None

    def digest(self) -> str:
        return _hash({
            "candidate_id": self.candidate_id,
            "decision_sha256": self.decision.digest(),
            "episode_sha256": self.episode.digest(),
        })


@dataclass(frozen=True, init=False)
class DeterministicDiversityCurriculum:
    """Immutable coverage policy with finite budgets and stable lexical tie-breaking.

    ``choose`` is pure and retry-idempotent. Persist the returned decision before execution;
    add durable practice history with ``observe`` before selecting the next decision. BRS uses
    ``choose_wave`` so one frozen wave never selects the same semantic task twice.
    """

    candidates: tuple[CurriculumCandidate, ...]
    history: tuple[CurriculumObservation, ...]
    max_attempts_per_candidate: int
    max_total_attempts: int
    _declared_candidates: tuple[CurriculumCandidate, ...]

    def __init__(
        self,
        candidates: Iterable[CurriculumCandidate],
        *,
        history: Iterable[CurriculumObservation] = (),
        max_attempts_per_candidate: int = 2,
        max_total_attempts: int = 32,
    ) -> None:
        declared = _bounded_items(candidates, _MAX_CANDIDATES, "candidates")
        observations = _bounded_items(history, _MAX_HISTORY, "history")
        if not declared or any(not isinstance(item, CurriculumCandidate) for item in declared):
            _fail("candidates_invalid")
        for budget in (max_attempts_per_candidate, max_total_attempts):
            if type(budget) is not int or not 1 <= budget <= _MAX_HISTORY:
                _fail("budget_invalid")
        by_id: dict[str, CurriculumCandidate] = {}
        for candidate in declared:
            if candidate.candidate_id in by_id and by_id[candidate.candidate_id] != candidate:
                _fail("candidate_id_conflict")
            by_id[candidate.candidate_id] = candidate
        normalized = tuple(sorted(by_id.values(), key=lambda item: (item.priority, item.candidate_id)))
        by_task: dict[str, CurriculumCandidate] = {}
        for candidate in normalized:
            by_task.setdefault(candidate.semantic_digest(), candidate)
        by_episode: dict[tuple[str, str], CurriculumObservation] = {}
        for observation in observations:
            if not isinstance(observation, CurriculumObservation):
                _fail("history_invalid")
            candidate = by_id.get(observation.candidate_id)
            if candidate is None or replace(observation.decision, reason_code="declared_practice") != candidate.decision():
                _fail("history_candidate_mismatch")
            key = (observation.episode.run_id, observation.episode.episode_id)
            if key in by_episode and by_episode[key] != observation:
                _fail("history_episode_conflict")
            by_episode[key] = observation
        object.__setattr__(self, "_declared_candidates", normalized)
        object.__setattr__(self, "candidates", tuple(by_task.values()))
        object.__setattr__(self, "history", tuple(by_episode[key] for key in sorted(by_episode)))
        object.__setattr__(self, "max_attempts_per_candidate", max_attempts_per_candidate)
        object.__setattr__(self, "max_total_attempts", max_total_attempts)
        self.fingerprint()  # Reject oversized catalogs before selection or persistence.

    def fingerprint(self) -> str:
        """Static declaration pin; history is separately pinned by ``history_fingerprint``."""
        return _hash({
            "policy": _POLICY_VERSION,
            "candidates": [candidate.to_dict() for candidate in self._declared_candidates],
            "max_attempts_per_candidate": self.max_attempts_per_candidate,
            "max_total_attempts": self.max_total_attempts,
        })

    def history_fingerprint(self) -> str:
        return _hash({"policy": self.fingerprint(), "history": [item.digest() for item in self.history]})

    def with_history(self, history: Iterable[CurriculumObservation]) -> DeterministicDiversityCurriculum:
        return type(self)(
            self._declared_candidates, history=history,
            max_attempts_per_candidate=self.max_attempts_per_candidate,
            max_total_attempts=self.max_total_attempts,
        )

    def with_observation(self, observation: CurriculumObservation) -> DeterministicDiversityCurriculum:
        return self.with_history((*self.history, observation))

    def observe(
        self, *, decision: CurriculumDecision, execution: EpisodeExecution,
    ) -> DeterministicDiversityCurriculum:
        semantic = replace(decision, reason_code="declared_practice").digest()
        candidate = next((item for item in self.candidates if item.semantic_digest() == semantic), None)
        if candidate is None:
            _fail("history_candidate_mismatch")
        return self.with_observation(CurriculumObservation.from_execution(candidate.candidate_id, decision, execution))

    def _ranked(self, *, target: PracticeEpisode, diagnosis: str) -> list[tuple[CurriculumCandidate, str]]:
        if not isinstance(target, PracticeEpisode):
            _fail("target_invalid")
        if type(diagnosis) is not str or len(diagnosis) > 8192:
            _fail("diagnosis_invalid")
        if target.status in {"unknown", "timed_out", "abandoned", "cancelled"}:
            _fail("target_unresolved")
        if len(self.history) >= self.max_total_attempts:
            _fail("budget_exhausted")
        declared = {item.candidate_id: item for item in self._declared_candidates}
        attempts: dict[str, int] = {}
        passed: set[str] = set()
        families: set[str] = set()
        boundaries: set[str] = set()
        failed_boundaries: set[str] = set()
        quarantined: set[str] = set()
        for observation in self.history:
            candidate, episode = declared[observation.candidate_id], observation.episode
            key = candidate.semantic_digest()
            attempts[key] = attempts.get(key, 0) + 1
            if any(getattr(episode, pin) != getattr(target, pin) for pin in (
                "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id",
            )):
                continue
            outcome = observation.verified_outcome
            if outcome == "pass":
                passed.add(key)
                families.add(candidate.practice_family)
                boundaries.add(candidate.failure_boundary)
            elif outcome == "fail":
                failed_boundaries.add(candidate.failure_boundary)
            else:
                quarantined.add(key)
        compatible = [item for item in self.candidates if target.solver_id in item.compatible_solvers]
        if not compatible:
            _fail("no_compatible_candidate")
        available = [item for item in compatible if (
            attempts.get(item.semantic_digest(), 0) < self.max_attempts_per_candidate
            and item.semantic_digest() not in quarantined
        )]
        if not available:
            _fail("history_unresolved" if quarantined else "budget_exhausted")
        diagnosis = diagnosis.casefold().strip()
        def score(candidate: CurriculumCandidate) -> tuple[Any, ...]:
            key = candidate.semantic_digest()
            repair = candidate.failure_boundary in failed_boundaries and key not in passed
            gap = candidate.capability_gap.casefold()
            matches_gap = bool(diagnosis) and (gap in diagnosis or diagnosis in gap)
            return (
                key in passed, not repair, candidate.practice_family in families,
                candidate.failure_boundary in boundaries, not matches_gap,
                attempts.get(key, 0), candidate.priority, candidate.candidate_id,
            )
        def reason(candidate: CurriculumCandidate) -> str:
            if candidate.failure_boundary in failed_boundaries and candidate.semantic_digest() not in passed:
                return "verified_failure_boundary"
            if candidate.practice_family not in families:
                return "uncovered_practice_family"
            if candidate.failure_boundary not in boundaries:
                return "uncovered_failure_boundary"
            return "least_attempted_declared_practice"
        return [(candidate, reason(candidate)) for candidate in sorted(available, key=score)]

    def choose(
        self, *, target: PracticeEpisode, diagnosis: str, wave: int, ordinal: int,
    ) -> CurriculumDecision:
        if type(wave) is not int or wave < 0 or type(ordinal) is not int or ordinal < 0:
            _fail("position_invalid")
        ranked = self._ranked(target=target, diagnosis=diagnosis)
        if ordinal >= len(ranked) or len(self.history) + ordinal >= self.max_total_attempts:
            _fail("budget_exhausted")
        candidate, reason = ranked[ordinal]
        return candidate.decision(reason)

    def choose_wave(
        self, *, target: PracticeEpisode, diagnosis: str, wave: int, count: int,
    ) -> tuple[CurriculumDecision, ...]:
        if type(count) is not int or not 1 <= count <= _MAX_CANDIDATES:
            _fail("wave_size_invalid")
        return tuple(self.choose(target=target, diagnosis=diagnosis, wave=wave, ordinal=i) for i in range(count))


DiversityFailureBoundaryCurriculum = DeterministicDiversityCurriculum

__all__ = [
    "CurriculumCandidate", "CurriculumObservation", "DeterministicDiversityCurriculum",
    "DiversityFailureBoundaryCurriculum",
]
