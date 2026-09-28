from dataclasses import FrozenInstanceError, replace

import pytest

from lunar_evolution.rsi_adapters import fixture_solver_gateway
from lunar_evolution.rsi_controller import PracticeEpisodeRunner
from lunar_evolution.rsi_curriculum import (
    CurriculumCandidate,
    CurriculumObservation,
    DeterministicDiversityCurriculum,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    PracticeEpisode,
    RSILearningError,
)

HEX = "a" * 64


def target(**kwargs):
    return replace(PracticeEpisode(
        "target", "run", HEX, HEX, HEX, EMPTY_MEMORY_SNAPSHOT_SHA256, "mock", "planned",
        episode_kind="target",
    ), **kwargs)


def candidate(identifier="a", *, family=None, boundary=None, gap=None, **kwargs):
    return CurriculumCandidate(
        identifier, family or f"family-{identifier}", gap or f"gap-{identifier}",
        f"strategy-{identifier}", f"expected-{identifier}", boundary or f"boundary-{identifier}",
        ("mock",), **kwargs,
    )


def execution(decision, *, episode_id="practice", status="completed", outcome="pass", **pins):
    episode = replace(target(**pins), episode_id=episode_id, episode_kind="practice")
    request = SolverRequest.build(
        episode_id=episode.episode_id, contract_sha256=episode.contract_sha256,
        evaluator_sha256=episode.evaluator_sha256, environment_sha256=episode.environment_sha256,
        memory_snapshot_sha256=episode.memory_snapshot_sha256, solver_id=episode.solver_id,
        practice_charter={**decision.to_dict(), "decision_sha256": decision.digest()},
    )
    result = PracticeEpisodeRunner(fixture_solver_gateway("mock", terminal_status=status)).run(episode, request)
    if status == "completed" and outcome != "pass":
        verifier = replace(
            result.verifier, outcome=outcome,
            checks=tuple(replace(check, outcome=outcome) for check in result.verifier.checks),
        )
        result = replace(result, episode=replace(result.episode, verifier=verifier), verifier=verifier)
    return result


def observe(policy, declared, **kwargs):
    decision = declared.decision()
    return policy.observe(decision=decision, execution=execution(decision, **kwargs))


def test_fingerprint_and_choice_are_independent_of_catalog_order_and_immutable():
    a, b = candidate("a"), candidate("b")
    first = DeterministicDiversityCurriculum([a, b])
    second = DeterministicDiversityCurriculum([b, a])
    assert first.fingerprint() == second.fingerprint()
    assert first.choose(target=target(), diagnosis="gap-b", wave=0, ordinal=0) == second.choose(
        target=target(), diagnosis="gap-b", wave=0, ordinal=0,
    )
    with pytest.raises(FrozenInstanceError):
        first.max_total_attempts = 100


def test_static_fingerprint_pins_every_declared_policy_input_and_history_has_own_pin():
    a = candidate()
    original = DeterministicDiversityCurriculum([a])
    changed = observe(original, a)
    assert changed.fingerprint() == original.fingerprint()
    assert changed.history_fingerprint() != original.history_fingerprint()
    for altered in (
        DeterministicDiversityCurriculum([replace(a, strategy="another strategy")]),
        DeterministicDiversityCurriculum([a], max_total_attempts=31),
        DeterministicDiversityCurriculum([a], max_attempts_per_candidate=3),
    ):
        assert original.fingerprint() != altered.fingerprint()


def test_verified_coverage_selects_new_family_before_matching_covered_family():
    covered = candidate("a", family="known")
    similar = candidate("b", family="known")
    novel = candidate("c", family="novel")
    policy = observe(DeterministicDiversityCurriculum([covered, similar, novel]), covered)
    chosen = policy.choose(target=target(), diagnosis=similar.capability_gap, wave=1, ordinal=0)
    assert chosen.practice_family == "novel"
    assert chosen.reason_code == "uncovered_practice_family"


def test_new_failure_boundary_is_preferred_within_verified_family():
    covered = candidate("a", family="known", boundary="known")
    reused = candidate("b", family="known", boundary="known")
    novel = candidate("c", family="known", boundary="new")
    policy = observe(DeterministicDiversityCurriculum([covered, reused, novel]), covered)
    chosen = policy.choose(target=target(), diagnosis=reused.capability_gap, wave=1, ordinal=0)
    assert chosen.failure_boundary == "new"
    assert chosen.reason_code == "uncovered_failure_boundary"


def test_verified_failure_boundary_drives_bounded_repair_before_unrelated_task():
    failing, novel = candidate("z", boundary="empty input"), candidate("a")
    policy = observe(DeterministicDiversityCurriculum([failing, novel]), failing, outcome="fail")
    chosen = policy.choose(target=target(), diagnosis="", wave=1, ordinal=0)
    assert chosen.failure_boundary == "empty input"
    assert chosen.reason_code == "verified_failure_boundary"
    policy = observe(policy, failing, outcome="fail", episode_id="retry")
    assert policy.choose(target=target(), diagnosis="", wave=2, ordinal=0).practice_family == novel.practice_family


@pytest.mark.parametrize("status", ["unknown", "timed_out", "abandoned", "cancelled", "failed"])
def test_uncertain_history_is_not_coverage_or_failure_and_is_quarantined(status):
    a, b = candidate("a", family="same"), candidate("b", family="same")
    policy = observe(DeterministicDiversityCurriculum([a, b]), a, status=status)
    chosen = policy.choose(target=target(), diagnosis=a.capability_gap, wave=1, ordinal=0)
    assert chosen.capability_gap == b.capability_gap
    assert chosen.reason_code == "uncovered_practice_family"
    with pytest.raises(RSILearningError, match="rsi_curriculum_history_unresolved"):
        observe(DeterministicDiversityCurriculum([a]), a, status=status).choose(
            target=target(), diagnosis="", wave=1, ordinal=0,
        )


def test_completed_unresolved_verifier_does_not_cover_family():
    a, b = candidate("a", family="same"), candidate("b", family="same")
    policy = observe(DeterministicDiversityCurriculum([a, b]), a, outcome="unresolved")
    assert policy.choose(target=target(), diagnosis="", wave=1, ordinal=0).reason_code == "uncovered_practice_family"


@pytest.mark.parametrize("pin", ["contract_sha256", "evaluator_sha256", "environment_sha256"])
def test_foreign_scope_pass_never_covers_current_task(pin):
    a, b = candidate("a"), candidate("b")
    policy = observe(DeterministicDiversityCurriculum([a, b]), a, **{pin: "b" * 64})
    chosen = policy.choose(target=target(), diagnosis=a.capability_gap, wave=1, ordinal=0)
    assert chosen.capability_gap == a.capability_gap
    assert chosen.reason_code == "uncovered_practice_family"


def test_history_replay_is_idempotent_but_conflicting_episode_is_rejected():
    a = candidate()
    decision = a.decision()
    observed = CurriculumObservation.from_execution("a", decision, execution(decision))
    once = DeterministicDiversityCurriculum([a], history=[observed])
    twice = once.with_observation(observed)
    assert once.history_fingerprint() == twice.history_fingerprint()
    assert len(twice.history) == 1
    conflicting = replace(observed, episode=replace(observed.episode, actor_fingerprint="c" * 64))
    with pytest.raises(RSILearningError, match="rsi_curriculum_history_episode_conflict"):
        once.with_observation(conflicting)


def test_equivalent_candidate_aliases_share_attempt_budget():
    a = candidate()
    alias = replace(a, candidate_id="alias")
    decision = alias.decision()
    observed = CurriculumObservation.from_execution("alias", decision, execution(decision, outcome="fail"))
    policy = DeterministicDiversityCurriculum([a, alias], history=[observed], max_attempts_per_candidate=1)
    assert len(policy.candidates) == 1
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_exhausted"):
        policy.choose(target=target(), diagnosis="", wave=0, ordinal=0)


def test_candidate_id_collision_is_rejected():
    a = candidate()
    with pytest.raises(RSILearningError, match="rsi_curriculum_candidate_id_conflict"):
        DeterministicDiversityCurriculum([a, replace(a, strategy="different")])


def test_duplicate_wave_tasks_are_deduplicated_and_finite():
    a, b = candidate("a"), candidate("b")
    policy = DeterministicDiversityCurriculum([a, a, replace(a, candidate_id="alias"), b])
    wave = policy.choose_wave(target=target(), diagnosis="", wave=0, count=2)
    assert [decision.capability_gap for decision in wave] == [a.capability_gap, b.capability_gap]
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_exhausted"):
        policy.choose_wave(target=target(), diagnosis="", wave=0, count=3)
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_exhausted"):
        DeterministicDiversityCurriculum([a, b], max_total_attempts=1).choose_wave(
            target=target(), diagnosis="", wave=0, count=2,
        )


def test_total_budget_counts_unknown_history_and_solver_incompatible_attempts():
    a, b = candidate("a"), candidate("b")
    policy = observe(DeterministicDiversityCurriculum([a, b], max_total_attempts=1), a, status="unknown")
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_exhausted"):
        policy.choose(target=target(), diagnosis="", wave=1, ordinal=0)


def test_unknown_target_is_blocked_and_solver_compatibility_is_enforced():
    policy = DeterministicDiversityCurriculum([candidate()])
    with pytest.raises(RSILearningError, match="rsi_curriculum_target_unresolved"):
        policy.choose(target=target(status="unknown"), diagnosis="", wave=0, ordinal=0)
    with pytest.raises(RSILearningError, match="rsi_curriculum_no_compatible_candidate"):
        policy.choose(target=target(solver_id="other"), diagnosis="", wave=0, ordinal=0)


def test_observation_requires_exact_charter_and_receipt_binding():
    a = candidate()
    decision = a.decision()
    result = execution(decision)
    with pytest.raises(RSILearningError, match="rsi_curriculum_observation_execution_mismatch"):
        CurriculumObservation.from_execution("a", replace(decision, strategy="changed"), result)
    changed_verifier = replace(result.verifier, candidate_receipt_sha256="b" * 64)
    changed = replace(result, verifier=changed_verifier, episode=replace(result.episode, verifier=changed_verifier))
    observed = CurriculumObservation.from_execution("a", decision, changed)
    assert observed.verified_outcome is None


@pytest.mark.parametrize("field,value", [
    ("max_total_attempts", 0), ("max_total_attempts", True),
    ("max_total_attempts", 257), ("max_attempts_per_candidate", -1),
])
def test_invalid_budget_is_rejected(field, value):
    with pytest.raises(RSILearningError, match="rsi_curriculum_budget_invalid"):
        DeterministicDiversityCurriculum([candidate()], **{field: value})


def test_candidate_iterable_is_bounded_before_materialization():
    def endless():
        while True:
            yield candidate()
    with pytest.raises(RSILearningError, match="rsi_curriculum_candidates_too_large"):
        DeterministicDiversityCurriculum(endless())
