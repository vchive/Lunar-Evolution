"""Focused provider-free tests for the failure-driven curriculum."""
from __future__ import annotations

import hashlib

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    FailureBoundaryPolicy,
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
            {"seed": "7", "budget": 2, "policy": curriculum.policy.to_dict(), "ledger": curriculum.to_ledger()},
            maximum=64 * 1024,
        )
    ).hexdigest()


def test_failure_boundary_policy_is_bounded_and_part_of_component_identity():
    policy = FailureBoundaryPolicy(
        prefer_uncovered_capability=True,
        hard_negative_after=1,
        max_cluster_selections=3,
        normal_novelty=95,
        hard_negative_novelty=70,
    )
    assert policy.to_dict() == {
        "policy_id": "failure-boundary-v1",
        "prefer_uncovered_capability": True,
        "hard_negative_after": 1,
        "max_cluster_selections": 3,
        "normal_novelty": 95,
        "hard_negative_novelty": 70,
    }
    assert policy.digest()
    curriculum = FailureDrivenCurriculum(seed="policy", budget=3, policy=policy)
    assert curriculum.rsi_fingerprint_config()["failure_boundary_policy"] == policy.to_dict()
    with pytest.raises(RSILearningError, match="rsi_curriculum_policy_invalid"):
        FailureBoundaryPolicy(hard_negative_after=4, max_cluster_selections=3)
    with pytest.raises(RSILearningError, match="rsi_curriculum_policy_invalid"):
        FailureBoundaryPolicy(normal_novelty=60, hard_negative_novelty=61)


def test_policy_prefers_uncovered_prerequisites_across_matching_failure_clusters():
    first = failure()
    second = FailureObservation(
        failure_code="wrong_type", capability="stable_sort",
        observable="type coercion changed", failure_boundary="mixed types only",
        practice_task="practice-types", transfer_task="holdout-types",
        prerequisites=("type_normalization",), hard_negative_task="negative-types",
    )
    curriculum = FailureDrivenCurriculum(
        seed="diversity", budget=4,
        failures=(first, second),
        policy=FailureBoundaryPolicy(prefer_uncovered_capability=True),
    )
    initial = curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    followup = curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=1)
    assert initial.practice_task == "practice-sort"
    assert followup.practice_task == "practice-types"
    assert followup.coverage == ("type_normalization",)
    assert followup.hard_negative is False


def test_policy_cluster_budget_fails_closed_before_another_side_effect():
    curriculum = FailureDrivenCurriculum(
        seed="cluster-budget", budget=3, failures=(failure(),),
        policy=FailureBoundaryPolicy(max_cluster_selections=2),
    )
    curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=1)
    with pytest.raises(RSILearningError, match="rsi_curriculum_cluster_budget_exhausted"):
        curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=2)
    assert curriculum.remaining_budget == 1
    assert len(curriculum.selections) == 2


@pytest.mark.parametrize("config", [
    {"policy_id": "custom"},
    {"prefer_uncovered_capability": 1},
    {"hard_negative_after": True},
    {"max_cluster_selections": 129},
    {"normal_novelty": 100.0},
    {"hard_negative_novelty": -1},
])
def test_policy_rejects_unknown_versions_and_noncanonical_parameters(config):
    with pytest.raises(RSILearningError, match="rsi_curriculum_policy_invalid"):
        FailureBoundaryPolicy(**config)


def test_policy_roundtrip_rejects_extra_fields_and_boolean_integer_substitution():
    policy = FailureBoundaryPolicy(hard_negative_after=3, max_cluster_selections=4)
    assert FailureBoundaryPolicy.from_dict(policy.to_dict()) == policy
    assert FailureBoundaryPolicy.from_dict(policy.to_dict()).digest() == policy.digest()
    with pytest.raises(RSILearningError, match="rsi_curriculum_policy_invalid"):
        FailureBoundaryPolicy.from_dict({**policy.to_dict(), "unknown": "field"})
    with pytest.raises(RSILearningError, match="rsi_curriculum_policy_invalid"):
        FailureBoundaryPolicy.from_dict({**policy.to_dict(), "prefer_uncovered_capability": 1})


def test_custom_boundary_threshold_preserves_diversity_before_hard_negatives():
    policy = FailureBoundaryPolicy(hard_negative_after=3, max_cluster_selections=4)
    curriculum = FailureDrivenCurriculum(seed="threshold", budget=4, failures=(failure(),), policy=policy)
    for ordinal in range(4):
        curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=ordinal)
    assert [item.practice_task for item in curriculum.selections] == [
        "practice-sort", "practice-sort:diversity:2", "practice-sort:diversity:3", "negative-sort",
    ]
    assert [item.hard_negative for item in curriculum.selections] == [False, False, False, True]
    assert [item.reason_code for item in curriculum.selections] == [
        "failure_cluster_gap", "failure_cluster_diversity", "failure_cluster_diversity", "failure_boundary_probe",
    ]
    restored = FailureDrivenCurriculum.from_ledger(curriculum.to_ledger(), seed="threshold", budget=4, policy=policy)
    assert restored.ledger_digest() == curriculum.ledger_digest()


def test_policy_uses_other_matching_cluster_before_exhaustion():
    other = FailureObservation(
        failure_code="wrong_type", capability="stable_sort",
        observable="type coercion changed", failure_boundary="mixed types only",
        practice_task="practice-types", transfer_task="holdout-types",
    )
    curriculum = FailureDrivenCurriculum(
        seed="cluster-fallback", budget=3, failures=(failure(), other),
        policy=FailureBoundaryPolicy(prefer_uncovered_capability=False, max_cluster_selections=1),
    )
    for ordinal in range(2):
        curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=ordinal)
    assert len({item.cluster_id for item in curriculum.selections}) == 2
    before = curriculum.to_ledger()
    with pytest.raises(RSILearningError, match="rsi_curriculum_cluster_budget_exhausted"):
        curriculum.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=2)
    assert curriculum.to_ledger() == before


def test_replay_rejects_policy_drift_even_when_previous_choices_could_match():
    original = FailureDrivenCurriculum(seed="drift", budget=4, failures=(failure(),))
    for ordinal in range(3):
        original.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=ordinal)
    with pytest.raises(RSILearningError, match="rsi_curriculum_ledger_identity_mismatch"):
        FailureDrivenCurriculum.from_ledger(
            original.to_ledger(), seed="drift", budget=4,
            policy=FailureBoundaryPolicy(max_cluster_selections=2),
        )


def test_ledger_digest_binds_policy_before_any_selection_exists():
    original = FailureDrivenCurriculum(seed="unselected", failures=(failure(),))
    alternate = FailureDrivenCurriculum.from_ledger(
        original.to_ledger(), seed="unselected", policy=FailureBoundaryPolicy(prefer_uncovered_capability=False),
    )
    assert original.to_ledger() == alternate.to_ledger()
    assert original.ledger_digest() != alternate.ledger_digest()


@pytest.mark.parametrize("field,value", [
    ("reason_code", "failure_boundary_probe"),
    ("coverage", []),
    ("transfer_task", "another-holdout"),
    ("diagnosis", "another-failure"),
])
def test_policy_replay_checks_reason_coverage_transfer_and_cluster_choice(field, value):
    original = FailureDrivenCurriculum(seed="replay-fields", budget=3, failures=(failure(),))
    original.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=0)
    ledger = list(original.to_ledger())
    ledger[-1][field] = value
    with pytest.raises(RSILearningError, match="rsi_curriculum_ledger_invalid"):
        FailureDrivenCurriculum.from_ledger(ledger, seed="replay-fields", budget=3)


def test_legacy_selection_ledger_is_bound_to_default_policy():
    original = FailureDrivenCurriculum(seed="legacy", budget=4, failures=(failure(),))
    for ordinal in range(3):
        original.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=ordinal)
    ledger = [{key: value for key, value in item.items() if key not in {"diagnosis", "policy_sha256"}}
              for item in original.to_ledger()]
    restored = FailureDrivenCurriculum.from_ledger(ledger, seed="legacy", budget=4)
    assert restored.to_ledger() == tuple(ledger)
    with pytest.raises(RSILearningError, match="rsi_curriculum_ledger_identity_mismatch"):
        FailureDrivenCurriculum.from_ledger(
            ledger, seed="legacy", budget=4, policy=FailureBoundaryPolicy(max_cluster_selections=2),
        )


def test_replay_rejects_forged_policy_binding_for_overbudget_ledger():
    original = FailureDrivenCurriculum(seed="bound", budget=4, failures=(failure(),))
    for ordinal in range(3):
        original.select(target=target(), diagnosis="stable_sort", wave=0, ordinal=ordinal)
    policy = FailureBoundaryPolicy(max_cluster_selections=2)
    ledger = list(original.to_ledger())
    for item in ledger:
        if item["kind"] == "selection":
            item["policy_sha256"] = policy.digest()
    with pytest.raises(RSILearningError, match="rsi_curriculum_ledger_invalid"):
        FailureDrivenCurriculum.from_ledger(ledger, seed="bound", budget=4, policy=policy)
