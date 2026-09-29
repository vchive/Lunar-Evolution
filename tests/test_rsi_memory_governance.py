import pytest

from lunar_evolution.rsi_learning import (
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from lunar_evolution.rsi_memory_governance import (
    MemoryAuthority,
    MemoryCompatibility,
    MemoryGovernanceAuthority,
    MemoryScope,
    PromotionGate,
)


def digest(index: int) -> str:
    return f"{index:064x}"


ACTOR = digest(900)
VERIFIER = digest(901)


def scope() -> MemoryScope:
    return MemoryScope("problem-family:sorting", "sorting", "stable-partition")


def compatibility() -> MemoryCompatibility:
    return MemoryCompatibility(digest(1), digest(2), digest(3), "native", digest(4))


def episode(memory_id: str = "memory-1", *, verified: bool = True) -> PracticeEpisode:
    pins = compatibility()
    result = (
        PracticeEpisode(
            f"episode-{memory_id}",
            "run-1",
            pins.contract_sha256,
            pins.evaluator_sha256,
            pins.environment_sha256,
            digest(8),
            pins.solver_id,
            "planned",
            solver_fingerprint=pins.solver_fingerprint,
        )
        .transition("running", request_sha256=digest(9))
        .transition(
            "completed",
            candidate_receipt_sha256=digest(50),
            execution_receipt_sha256=digest(51),
            official_evaluation_receipt_sha256=digest(7),
            trace_digest=digest(52),
        )
    )
    if not verified:
        return result
    return result.attach_verifier(
        VerifierDecision(
            result.episode_id,
            "pass",
            digest(10),
            "independently verified candidate",
            VERIFIER,
            (VerifierCheck("official_evaluator", "pass", digest(7)),),
            contract_sha256=pins.contract_sha256,
            evaluator_sha256=pins.evaluator_sha256,
            environment_sha256=pins.environment_sha256,
            official_evaluation_receipt_sha256=digest(7),
            candidate_receipt_sha256=digest(50),
            execution_receipt_sha256=digest(51),
            evidence_sha256=digest(53),
        )
    )


def authority(
    memory_id: str = "memory-1", *, source_episode: PracticeEpisode | None = None
) -> MemoryAuthority:
    source_episode = source_episode or episode(memory_id)
    return MemoryAuthority(
        memory_id,
        digest(5),
        f"episode-{memory_id}",
        source_episode.digest(),
        digest(7),
        digest(8),
        scope(),
        compatibility(),
    )


def gate(
    source: MemoryAuthority,
    *,
    practice_count: int = 2,
    baseline_holdout_score: int = 10,
    challenger_holdout_score: int = 11,
    compatibility_fingerprint: str | None = None,
    parent_snapshot_sha256: str | None = None,
    failures: tuple[str, ...] = (),
) -> PromotionGate:
    practice = (source.source_receipt_sha256,) + tuple(
        digest(20 + index) for index in range(practice_count - 1)
    )
    holdout = (digest(40),)
    return PromotionGate(
        compatibility_fingerprint or source.compatibility.digest(),
        parent_snapshot_sha256 or source.parent_snapshot_sha256,
        digest(30),
        source.source_receipt_sha256,
        digest(31),
        holdout[0],
        10,
        11,
        baseline_holdout_score,
        challenger_holdout_score,
        practice,
        holdout,
        failures,
    )


def candidate_in_shadow(governance: MemoryGovernanceAuthority, source: MemoryAuthority):
    observed = governance.observe(
        source, observation_receipt_sha256=source.source_receipt_sha256, actor_fingerprint=ACTOR
    )
    verified = governance.verify(
        observed,
        source_episode=episode(source.memory_id),
        transition_receipt_sha256=digest(11),
        actor_fingerprint=ACTOR,
    )
    candidate = governance.nominate_candidate(
        verified, transition_receipt_sha256=digest(12), actor_fingerprint=ACTOR
    )
    return governance.start_shadow(
        candidate, transition_receipt_sha256=digest(13), actor_fingerprint=ACTOR
    )


def activate(governance: MemoryGovernanceAuthority, source: MemoryAuthority):
    shadow = candidate_in_shadow(governance, source)
    approved = governance.approve(
        shadow, gate(source), transition_receipt_sha256=digest(14), actor_fingerprint=ACTOR
    )
    return governance.activate(
        approved, transition_receipt_sha256=digest(15), actor_fingerprint=ACTOR
    )


def test_lifecycle_binds_source_scope_compatibility_parent_and_receipts():
    governance = MemoryGovernanceAuthority()
    source = authority()
    active = activate(governance, source)

    assert active.state == "active"
    assert active.authority.source_episode_id == "episode-memory-1"
    assert active.authority.parent_snapshot_sha256 == digest(8)
    assert active.verifier_receipt_sha256 == digest(10)
    assert [receipt.state for receipt in active.receipts] == [
        "observed",
        "verified",
        "candidate",
        "shadow",
        "approved",
        "active",
    ]
    assert active.to_dict()["record_sha256"] == active.digest()
    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == (active,)


def test_single_practice_pass_can_be_approved_pending_but_never_activated():
    governance = MemoryGovernanceAuthority()
    source = authority()
    shadow = candidate_in_shadow(governance, source)
    approved = governance.approve(
        shadow,
        gate(source, practice_count=1),
        transition_receipt_sha256=digest(14),
        actor_fingerprint=ACTOR,
    )

    assert approved.state == "approved"
    with pytest.raises(RSILearningError, match="rsi_memory_activation_evidence_insufficient"):
        governance.activate(approved, transition_receipt_sha256=digest(15), actor_fingerprint=ACTOR)
    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == ()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"challenger_holdout_score": 9}, "rsi_memory_gate_regression"),
        ({"compatibility_fingerprint": digest(99)}, "rsi_memory_gate_compatibility_mismatch"),
        ({"parent_snapshot_sha256": digest(98)}, "rsi_memory_gate_parent_snapshot_mismatch"),
        ({"failures": (digest(80),)}, "rsi_memory_gate_regression"),
    ],
)
def test_holdout_regression_or_fingerprint_drift_cannot_be_approved(kwargs, error):
    governance = MemoryGovernanceAuthority()
    source = authority()
    shadow = candidate_in_shadow(governance, source)

    with pytest.raises(RSILearningError, match=error):
        governance.approve(
            shadow,
            gate(source, **kwargs),
            transition_receipt_sha256=digest(14),
            actor_fingerprint=ACTOR,
        )


def test_revoked_and_quarantined_memory_are_excluded_from_new_retrieval():
    governance = MemoryGovernanceAuthority()
    source = authority()
    active = activate(governance, source)
    revoked = governance.revoke(
        active, transition_receipt_sha256=digest(16), actor_fingerprint=ACTOR
    )

    assert revoked.state == "revoked"
    assert revoked.verifier_receipt_sha256 == active.verifier_receipt_sha256
    assert revoked.gate == active.gate
    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == ()

    source_two = authority("memory-2")
    shadow = candidate_in_shadow(governance, source_two)
    quarantined = governance.quarantine(
        shadow, transition_receipt_sha256=digest(17), actor_fingerprint=ACTOR
    )
    assert quarantined.state == "quarantined"
    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == ()


def test_active_conflict_requires_explicit_deprecation_of_existing_champion():
    governance = MemoryGovernanceAuthority()
    champion = activate(governance, authority("champion"))
    challenger_source = authority("challenger")
    challenger_shadow = candidate_in_shadow(governance, challenger_source)
    challenger = governance.approve(
        challenger_shadow,
        gate(challenger_source),
        transition_receipt_sha256=digest(114),
        actor_fingerprint=ACTOR,
    )

    with pytest.raises(RSILearningError, match="rsi_memory_active_conflict"):
        governance.activate(
            challenger, transition_receipt_sha256=digest(115), actor_fingerprint=ACTOR
        )

    deprecated = governance.deprecate(
        champion, transition_receipt_sha256=digest(116), actor_fingerprint=ACTOR
    )
    active = governance.activate(
        challenger, transition_receipt_sha256=digest(117), actor_fingerprint=ACTOR
    )
    assert deprecated.state == "deprecated"
    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == (active,)


def test_lifecycle_is_strict_and_rejects_stale_or_unverified_promotions():
    governance = MemoryGovernanceAuthority()
    source = authority()
    observed = governance.observe(
        source, observation_receipt_sha256=source.source_receipt_sha256, actor_fingerprint=ACTOR
    )

    with pytest.raises(RSILearningError, match="rsi_memory_lifecycle_state_invalid"):
        governance.nominate_candidate(
            observed, transition_receipt_sha256=digest(12), actor_fingerprint=ACTOR
        )
    with pytest.raises(RSILearningError, match="rsi_memory_verifier_episode_mismatch"):
        governance.verify(
            observed,
            source_episode=episode("other"),
            transition_receipt_sha256=digest(11),
            actor_fingerprint=ACTOR,
        )

    verified = governance.verify(
        observed,
        source_episode=episode(),
        transition_receipt_sha256=digest(11),
        actor_fingerprint=ACTOR,
    )
    with pytest.raises(RSILearningError, match="rsi_memory_stale_record"):
        governance.verify(
            observed,
            source_episode=episode(),
            transition_receipt_sha256=digest(18),
            actor_fingerprint=ACTOR,
        )
    assert verified.state == "verified"


def test_unverified_episode_is_never_accepted_as_promotion_evidence():
    governance = MemoryGovernanceAuthority()
    source_episode = episode(verified=False)
    source = authority(source_episode=source_episode)
    observed = governance.observe(
        source, observation_receipt_sha256=source.source_receipt_sha256, actor_fingerprint=ACTOR
    )

    with pytest.raises(RSILearningError, match="rsi_memory_verifier_not_passed"):
        governance.verify(
            observed,
            source_episode=source_episode,
            transition_receipt_sha256=digest(11),
            actor_fingerprint=ACTOR,
        )


def test_holdout_tie_cannot_activate_without_observed_transfer_improvement():
    governance = MemoryGovernanceAuthority()
    source = authority()
    shadow = candidate_in_shadow(governance, source)
    approved = governance.approve(
        shadow,
        gate(source, baseline_holdout_score=10, challenger_holdout_score=10),
        transition_receipt_sha256=digest(14),
        actor_fingerprint=ACTOR,
    )
    with pytest.raises(RSILearningError, match="rsi_memory_activation_evidence_insufficient"):
        governance.activate(approved, transition_receipt_sha256=digest(15), actor_fingerprint=ACTOR)
