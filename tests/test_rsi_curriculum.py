"""Focused provider-free tests for the failure-driven curriculum."""
from __future__ import annotations

import hashlib

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    FailureDrivenCurriculum,
    FailureObservation,
    RSILearningError,
    RSIPracticeEpisode,
)

HEX = "a" * 64


def target() -> RSIPracticeEpisode:
    return RSIPracticeEpisode(
        episode_id="target-1", run_id="run-1", contract_sha256=HEX,
        evaluator_sha256=HEX, environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256,
        solver_id="mock", status="planned", episode_kind="target",
    )


def failure(*, task: str = "practice-sort", hard_negative: str | None = "negative-sort") -> FailureObservation:
    return FailureObservation(
        failure_code="wrong_order", capability="stable_sort",
        observable="duplicate order changed", failure_boundary="duplicates only",
        practice_task=task, transfer_task="holdout-sort",
        prerequisites=("comparison",), hard_negative_task=hard_negative,
    )


def test_failure_clusters_are_idempotent_and_selection_is_auditable():
    curriculum = FailureDrivenCurriculum(seed="s1", budget=4)
    cluster_id = curriculum.record_failure(failure())
    assert curriculum.record_failure(failure()) == cluster_id
    assert curriculum.clusters()[0].observation_count == 1

    decision = curriculum.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    selection = curriculum.selections[-1]
    assert decision.reason_code == "failure_cluster_gap"
    assert selection.coverage == ("comparison", "stable_sort")
    assert selection.novelty == 100
    assert selection.budget == {"limit": 4, "before": 4, "after": 3, "remaining": 3}
    assert selection.to_dict()["reason_code"] == decision.reason_code


def test_repeated_failure_selects_boundary_hard_negative_without_duplicate_task():
    curriculum = FailureDrivenCurriculum(seed=0, budget=4, failures=(failure(),))
    first = curriculum.choose(target=target(), diagnosis="wrong_order", wave=0, ordinal=0)
    second = curriculum.choose(target=target(), diagnosis="wrong_order", wave=0, ordinal=1)
    third = curriculum.choose(target=target(), diagnosis="wrong_order", wave=0, ordinal=2)

    assert first.practice_family == "practice-sort"
    assert second.practice_family == "negative-sort"
    assert third.practice_family == "negative-sort:2"
    assert curriculum.selections[1].hard_negative is True
    assert curriculum.selections[1].reason_code == "failure_boundary_probe"
    assert len({item.practice_task for item in curriculum.selections}) == 3


def test_curriculum_component_fingerprint_excludes_mutable_ledger_state():
    curriculum = FailureDrivenCurriculum(seed="stable", budget=2, failures=(failure(),))
    identity = curriculum.rsi_fingerprint_config()
    curriculum.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    assert curriculum.rsi_fingerprint_config() == identity


def test_same_seed_and_ledger_replay_the_next_selection_exactly():
    original = FailureDrivenCurriculum(seed=91, budget=5, failures=(failure(),))
    original.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    original.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=1)
    ledger = original.to_ledger()

    replay = FailureDrivenCurriculum.from_ledger(ledger, seed=91, budget=5)
    expected = original.choose(target=target(), diagnosis="stable_sort", wave=1, ordinal=2)
    actual = replay.choose(target=target(), diagnosis="stable_sort", wave=1, ordinal=2)
    assert actual.to_dict() == expected.to_dict()
    assert replay.ledger_digest() == original.ledger_digest()


def test_budget_is_fail_closed_and_ledger_tampering_is_rejected():
    curriculum = FailureDrivenCurriculum(seed="budget", budget=1, failures=(failure(),))
    curriculum.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_exhausted"):
        curriculum.choose(target=target(), diagnosis="stable_sort", wave=0, ordinal=1)

    ledger = list(curriculum.to_ledger())
    ledger[-1] = dict(ledger[-1])
    ledger[-1]["novelty"] = 99
    with pytest.raises(RSILearningError, match="rsi_curriculum_ledger_invalid"):
        FailureDrivenCurriculum.from_ledger(ledger, seed="budget", budget=1)


def test_ledger_digest_is_canonical_and_does_not_use_process_details():
    curriculum = FailureDrivenCurriculum(seed=7, budget=2, failures=(failure(),))
    first = curriculum.ledger_digest()
    assert first == hashlib.sha256(
        __import__("lunar_evolution.candidate_evaluation_spec", fromlist=["canonical_json"]).canonical_json(
            {"seed": "7", "budget": 2, "ledger": curriculum.to_ledger()}, maximum=64 * 1024,
        )
    ).hexdigest()
