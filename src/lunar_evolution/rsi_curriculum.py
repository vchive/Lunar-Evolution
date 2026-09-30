"""Deterministic, provider-free failure-driven RSI curriculum.

This module keeps curriculum state separate from solver execution and memory snapshots.  It mines
small structured failure observations into stable clusters, suppresses repeated practice tasks,
and records every choice in a canonical ledger that can be replayed with the same seed.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_controller import CurriculumDecision
from .rsi_learning import PracticeEpisode, RSILearningError

_MAX_TEXT = 4096
_MAX_ITEMS = 128


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value or len(value.encode("utf-8")) > _MAX_TEXT:
        raise RSILearningError(f"rsi_curriculum_{name}_invalid")
    return value.strip()


def _items(value: object, name: str, maximum: int = 32) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > maximum:
        raise RSILearningError(f"rsi_curriculum_{name}_invalid")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise RSILearningError(f"rsi_curriculum_{name}_invalid")
    return result


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=64 * 1024)).hexdigest()


@dataclass(frozen=True)
class FailureObservation:
    """Public, bounded failure ontology used by the narrow curriculum policy."""

    failure_code: str
    capability: str
    observable: str
    failure_boundary: str
    practice_task: str
    transfer_task: str
    prerequisites: tuple[str, ...] = ()
    hard_negative_task: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.failure_code, "failure_code"),
            (self.capability, "capability"),
            (self.observable, "observable"),
            (self.failure_boundary, "failure_boundary"),
            (self.practice_task, "practice_task"),
            (self.transfer_task, "transfer_task"),
        ):
            _text(value, name)
        object.__setattr__(self, "prerequisites", _items(self.prerequisites, "prerequisites"))
        if self.hard_negative_task is not None:
            object.__setattr__(self, "hard_negative_task", _text(self.hard_negative_task, "hard_negative_task"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_code": self.failure_code,
            "capability": self.capability,
            "observable": self.observable,
            "failure_boundary": self.failure_boundary,
            "practice_task": self.practice_task,
            "transfer_task": self.transfer_task,
            "prerequisites": list(self.prerequisites),
            "hard_negative_task": self.hard_negative_task,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FailureObservation:
        required = {"failure_code", "capability", "observable", "failure_boundary", "practice_task", "transfer_task"}
        allowed = required | {"prerequisites", "hard_negative_task"}
        if not isinstance(value, Mapping) or not required.issubset(value) or set(value) - allowed:
            raise RSILearningError("rsi_curriculum_failure_observation_invalid")
        return cls(
            value["failure_code"], value["capability"], value["observable"], value["failure_boundary"],
            value["practice_task"], value["transfer_task"], tuple(value.get("prerequisites", ())),
            value.get("hard_negative_task"),
        )

    def cluster_id(self) -> str:
        # Exclude free-form task wording so equivalent observed failures cluster together.
        return "failure-cluster-" + _digest({
            "failure_code": self.failure_code,
            "capability": self.capability,
            "observable": self.observable,
            "failure_boundary": self.failure_boundary,
        })


@dataclass(frozen=True)
class FailureCluster:
    cluster_id: str
    representative: FailureObservation
    observation_count: int
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.cluster_id.startswith("failure-cluster-") or self.observation_count < 1:
            raise RSILearningError("rsi_curriculum_cluster_invalid")
        if len(self.observation_ids) != self.observation_count:
            raise RSILearningError("rsi_curriculum_cluster_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "representative": self.representative.to_dict(),
            "observation_count": self.observation_count,
            "observation_ids": list(self.observation_ids),
        }


@dataclass(frozen=True)
class CurriculumSelection:
    """Auditable result of one deterministic task choice."""

    selection_id: str
    cluster_id: str
    practice_task: str
    transfer_task: str
    reason_code: str
    coverage: tuple[str, ...]
    novelty: int
    budget_limit: int
    budget_before: int
    budget_after: int
    hard_negative: bool
    seed: str
    ordinal: int

    def __post_init__(self) -> None:
        _text(self.selection_id, "selection_id")
        _text(self.cluster_id, "cluster_id")
        _text(self.practice_task, "practice_task")
        _text(self.transfer_task, "transfer_task")
        _text(self.reason_code, "reason_code")
        object.__setattr__(self, "coverage", _items(self.coverage, "coverage"))
        if type(self.novelty) is not int or not 0 <= self.novelty <= 100:
            raise RSILearningError("rsi_curriculum_novelty_invalid")
        if type(self.budget_limit) is not int or self.budget_limit < 1:
            raise RSILearningError("rsi_curriculum_budget_invalid")
        if type(self.budget_before) is not int or type(self.budget_after) is not int:
            raise RSILearningError("rsi_curriculum_budget_invalid")
        if self.budget_before < 1 or self.budget_after != self.budget_before - 1:
            raise RSILearningError("rsi_curriculum_budget_invalid")
        if self.budget_before > self.budget_limit or self.budget_after < 0:
            raise RSILearningError("rsi_curriculum_budget_invalid")
        if type(self.hard_negative) is not bool or type(self.ordinal) is not int or self.ordinal < 0:
            raise RSILearningError("rsi_curriculum_selection_invalid")
        _text(self.seed, "seed")

    @property
    def budget(self) -> dict[str, int]:
        return {
            "limit": self.budget_limit,
            "before": self.budget_before,
            "after": self.budget_after,
            "remaining": self.budget_after,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_id": self.selection_id,
            "cluster_id": self.cluster_id,
            "practice_task": self.practice_task,
            "transfer_task": self.transfer_task,
            "reason_code": self.reason_code,
            "coverage": list(self.coverage),
            "novelty": self.novelty,
            "budget": self.budget,
            "hard_negative": self.hard_negative,
            "seed": self.seed,
            "ordinal": self.ordinal,
        }


class FailureDrivenCurriculum:
    """A deterministic failure-driven policy with no provider or evaluator dependency.

    ``record_failure`` is the only input mutation.  ``choose`` implements the existing
    ``Curriculum`` protocol and records an auditable selection.  ``to_ledger`` and
    ``from_ledger`` provide exact local replay; no timestamps or process identity enter the digest.
    """

    def __init__(
        self,
        *,
        seed: str | int = 0,
        budget: int = 32,
        failures: Sequence[FailureObservation] = (),
        ledger: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        if type(seed) not in {str, int}:
            raise RSILearningError("rsi_curriculum_seed_invalid")
        self.seed = str(seed)
        if type(budget) is not int or budget < 1 or budget > _MAX_ITEMS:
            raise RSILearningError("rsi_curriculum_budget_invalid")
        self.budget_limit = budget
        self._budget_used = 0
        self._observations: dict[str, FailureObservation] = {}
        self._clusters: dict[str, list[str]] = {}
        self._selected_tasks: set[tuple[str, str]] = set()
        self._covered: set[str] = set()
        self._selections: list[CurriculumSelection] = []
        self._ledger: list[dict[str, Any]] = []
        for failure in failures:
            self.record_failure(failure)
        if ledger is not None:
            self._load_ledger(ledger)

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        # Ledger state belongs to the durable run checkpoint; component identity must remain
        # stable while selections are appended, otherwise a normal resume looks like code drift.
        return {"policy": "failure-driven-v1", "seed": self.seed, "budget": self.budget_limit}

    @property
    def remaining_budget(self) -> int:
        return self.budget_limit - self._budget_used

    @property
    def selections(self) -> tuple[CurriculumSelection, ...]:
        return tuple(self._selections)

    def clusters(self) -> tuple[FailureCluster, ...]:
        return tuple(
            FailureCluster(cluster_id, self._observations[ids[0]], len(ids), tuple(ids))
            for cluster_id, ids in sorted(self._clusters.items())
        )

    def record_failure(self, failure: FailureObservation) -> str:
        if not isinstance(failure, FailureObservation):
            raise RSILearningError("rsi_curriculum_failure_observation_invalid")
        observation_id = _digest(failure.to_dict())
        cluster_id = failure.cluster_id()
        # Same evidence is an idempotent observation; a repeated occurrence with the same
        # normalized payload still increments clustering only when it has a distinct ledger id.
        if observation_id not in self._observations:
            self._observations[observation_id] = failure
            self._clusters.setdefault(cluster_id, []).append(observation_id)
            self._ledger.append({"kind": "failure", "observation_id": observation_id, "observation": failure.to_dict()})
        return cluster_id

    def _find_cluster(self, diagnosis: str) -> FailureCluster:
        text = _text(diagnosis or "target capability gap", "diagnosis")
        matches = [cluster for cluster in self.clusters() if text in {
            cluster.representative.failure_code,
            cluster.representative.capability,
            cluster.representative.observable,
            cluster.representative.practice_task,
        }]
        if matches:
            return min(matches, key=lambda item: item.cluster_id)
        synthetic = FailureObservation(
            failure_code=text, capability=text, observable=text,
            failure_boundary="boundary requires independent verification",
            practice_task=f"practice:{text}", transfer_task=f"transfer:{text}",
        )
        cluster_id = self.record_failure(synthetic)
        return self.clusters()[next(index for index, item in enumerate(self.clusters()) if item.cluster_id == cluster_id)]

    def select(self, *, target: PracticeEpisode, diagnosis: str, wave: int, ordinal: int) -> CurriculumSelection:
        if not isinstance(target, PracticeEpisode) or type(wave) is not int or wave < 0 or type(ordinal) is not int or ordinal < 0:
            raise RSILearningError("rsi_curriculum_selection_invalid")
        if self.remaining_budget <= 0:
            raise RSILearningError("rsi_curriculum_budget_exhausted")
        cluster = self._find_cluster(diagnosis)
        representative = cluster.representative
        repeat_count = sum(1 for cluster_id, _task in self._selected_tasks if cluster_id == cluster.cluster_id)
        base_task = representative.practice_task
        task = base_task
        hard_negative = False
        reason_code = "failure_cluster_gap"
        if (cluster.cluster_id, task) in self._selected_tasks or repeat_count >= 1:
            hard_negative = True
            reason_code = "failure_boundary_probe" if repeat_count >= 1 else "hard_negative"
            task = representative.hard_negative_task or f"{base_task}:boundary"
        if (cluster.cluster_id, task) in self._selected_tasks:
            # Never emit a duplicate practice task.  The suffix is deterministic and carries the
            # repeated-failure ordinal into a new boundary probe identity.
            boundary_count = sum(
                1 for cluster_id, selected_task in self._selected_tasks
                if cluster_id == cluster.cluster_id and selected_task.startswith(task + ":")
            )
            task = f"{task}:{boundary_count + 2}"
            reason_code = "failure_boundary_probe"
        coverage = tuple(sorted({representative.capability, *representative.prerequisites}))
        new_coverage = tuple(item for item in coverage if item not in self._covered)
        novelty = 100 if (cluster.cluster_id, task) not in self._selected_tasks else 0
        if hard_negative and novelty == 100:
            novelty = 80
        before = self.remaining_budget
        self._budget_used += 1
        selection_id = "rsi-selection-" + _digest({
            "seed": self.seed, "cluster_id": cluster.cluster_id, "task": task,
            "ordinal": ordinal, "used": self._budget_used,
        })
        selected = CurriculumSelection(
            selection_id, cluster.cluster_id, task, representative.transfer_task, reason_code,
            new_coverage, novelty, self.budget_limit, before, self.remaining_budget,
            hard_negative, self.seed, ordinal,
        )
        self._selected_tasks.add((cluster.cluster_id, task))
        self._covered.update(coverage)
        self._selections.append(selected)
        self._ledger.append({"kind": "selection", **selected.to_dict()})
        return selected

    def choose(self, *, target: PracticeEpisode, diagnosis: str, wave: int, ordinal: int) -> CurriculumDecision:
        selected = self.select(target=target, diagnosis=diagnosis, wave=wave, ordinal=ordinal)
        cluster = next(item for item in self.clusters() if item.cluster_id == selected.cluster_id)
        representative = cluster.representative
        strategy = (
            f"execute {selected.practice_task}; verify boundary before retrying the target"
            if selected.hard_negative else f"execute {selected.practice_task} to cover the clustered failure"
        )
        return CurriculumDecision(
            practice_family=selected.practice_task,
            capability_gap=representative.capability,
            reason_code=selected.reason_code,
            strategy=strategy,
            expected_result=f"cover capability {representative.capability} on {selected.transfer_task}",
            failure_boundary=representative.failure_boundary,
            compatible_solvers=(target.solver_id,),
        )

    def to_ledger(self) -> tuple[dict[str, Any], ...]:
        return tuple(json.loads(json.dumps(item, sort_keys=True, separators=(",", ":"))) for item in self._ledger)

    def ledger_digest(self) -> str:
        return _digest({"seed": self.seed, "budget": self.budget_limit, "ledger": self._ledger})

    @classmethod
    def from_ledger(
        cls, ledger: Sequence[Mapping[str, Any]] | bytes | str, *, seed: str | int,
        budget: int | None = None,
    ) -> FailureDrivenCurriculum:
        if isinstance(ledger, bytes):
            try:
                ledger = json.loads(ledger.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RSILearningError("rsi_curriculum_ledger_invalid") from exc
        elif isinstance(ledger, str):
            try:
                ledger = json.loads(ledger)
            except json.JSONDecodeError as exc:
                raise RSILearningError("rsi_curriculum_ledger_invalid") from exc
        if isinstance(ledger, (str, bytes)) or not isinstance(ledger, Sequence):
            raise RSILearningError("rsi_curriculum_ledger_invalid")
        if budget is None:
            limits = {
                item.get("budget", {}).get("limit") for item in ledger
                if isinstance(item, Mapping) and item.get("kind") == "selection"
                and isinstance(item.get("budget"), Mapping)
            }
            if len(limits) == 1:
                budget = next(iter(limits))
            else:
                budget = 32
        return cls(seed=seed, budget=budget, ledger=ledger)

    def _load_ledger(self, ledger: Sequence[Mapping[str, Any]]) -> None:
        if len(ledger) > _MAX_ITEMS:
            raise RSILearningError("rsi_curriculum_ledger_invalid")
        for raw in ledger:
            if not isinstance(raw, Mapping) or raw.get("kind") not in {"failure", "selection"}:
                raise RSILearningError("rsi_curriculum_ledger_invalid")
            if raw["kind"] == "failure":
                if set(raw) != {"kind", "observation_id", "observation"}:
                    raise RSILearningError("rsi_curriculum_ledger_invalid")
                failure = FailureObservation.from_dict(raw.get("observation", {}))
                observed_id = _digest(failure.to_dict())
                if raw.get("observation_id") != observed_id:
                    raise RSILearningError("rsi_curriculum_ledger_invalid")
                self.record_failure(failure)
                continue
            # Selection events are restored as evidence, not replayed as a new budget charge.
            required = {"selection_id", "cluster_id", "practice_task", "transfer_task", "reason_code", "coverage", "novelty", "budget", "hard_negative", "seed", "ordinal"}
            if set(raw) - ({"kind"} | required) or not required.issubset(raw):
                raise RSILearningError("rsi_curriculum_ledger_invalid")
            budget = raw["budget"]
            if (not isinstance(budget, Mapping)
                    or set(budget) != {"limit", "before", "after", "remaining"}
                    or not isinstance(raw["coverage"], list)):
                raise RSILearningError("rsi_curriculum_ledger_invalid")
            if raw["seed"] != self.seed or budget.get("limit") != self.budget_limit:
                raise RSILearningError("rsi_curriculum_ledger_identity_mismatch")
            before, after = budget.get("before"), budget.get("after")
            if budget.get("remaining") != after:
                raise RSILearningError("rsi_curriculum_ledger_invalid")
            selected = CurriculumSelection(
                raw["selection_id"], raw["cluster_id"], raw["practice_task"], raw["transfer_task"],
                raw["reason_code"], tuple(raw["coverage"]), raw["novelty"], self.budget_limit,
                before, after, raw["hard_negative"], raw["seed"], raw["ordinal"],
            )
            expected_id = "rsi-selection-" + _digest({
                "seed": self.seed, "cluster_id": selected.cluster_id,
                "task": selected.practice_task, "ordinal": selected.ordinal,
                "used": self.budget_limit - selected.budget_after,
            })
            expected_novelty = 80 if selected.hard_negative else 100
            expected_before = self.budget_limit - len(self._selections)
            if (selected.cluster_id not in self._clusters
                    or selected.selection_id in {item.selection_id for item in self._selections}
                    or selected.selection_id != expected_id
                    or selected.novelty != expected_novelty
                    or selected.budget_before != expected_before):
                raise RSILearningError("rsi_curriculum_ledger_invalid")
            self._selections.append(selected)
            self._selected_tasks.add((selected.cluster_id, selected.practice_task))
            self._covered.update(selected.coverage)
            self._budget_used += 1
            if self._budget_used > self.budget_limit:
                raise RSILearningError("rsi_curriculum_budget_invalid")
            self._ledger.append(dict(raw))


__all__ = ["CurriculumSelection", "FailureCluster", "FailureDrivenCurriculum", "FailureObservation"]
