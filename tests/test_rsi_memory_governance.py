import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
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
    MemoryPromotionRecord,
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


def promotion_record(state: str):
    governance = MemoryGovernanceAuthority()
    source = authority()
    shadow = candidate_in_shadow(governance, source)
    approved = governance.approve(
        shadow, gate(source), transition_receipt_sha256=digest(14), actor_fingerprint=ACTOR
    )
    if state == "approved":
        return approved
    active = governance.activate(
        approved, transition_receipt_sha256=digest(15), actor_fingerprint=ACTOR
    )
    if state == "active":
        return active
    transition = {
        "deprecated": governance.deprecate,
        "revoked": governance.revoke,
        "quarantined": governance.quarantine,
    }[state]
    return transition(active, transition_receipt_sha256=digest(16), actor_fingerprint=ACTOR)


def promotion_history(
    state: str = "active", *, source: MemoryAuthority | None = None, terminal_from: str = "active"
) -> tuple[MemoryPromotionRecord, ...]:
    governance = MemoryGovernanceAuthority()
    source = source or authority()
    result = [
        governance.observe(
            source, observation_receipt_sha256=source.source_receipt_sha256, actor_fingerprint=ACTOR
        )
    ]
    target = terminal_from if state in {"deprecated", "revoked", "quarantined"} else state
    steps = (
        (governance.verify, {"source_episode": episode(source.memory_id)}),
        (governance.nominate_candidate, {}),
        (governance.start_shadow, {}),
        (governance.approve, {"gate": gate(source)}),
        (governance.activate, {}),
    )
    for index, (action, kwargs) in enumerate(steps):
        if result[-1].state == target:
            break
        result.append(
            action(
                result[-1],
                transition_receipt_sha256=digest(11 + index),
                actor_fingerprint=ACTOR,
                **kwargs,
            )
        )
    if state != target:
        action = {
            "deprecated": governance.deprecate,
            "revoked": governance.revoke,
            "quarantined": governance.quarantine,
        }[state]
        result.append(
            action(result[-1], transition_receipt_sha256=digest(18), actor_fingerprint=ACTOR)
        )
    assert result[-1].state == state
    return tuple(result)


def rehash_wire_record(value: dict) -> dict:
    value["record_sha256"] = hashlib.sha256(
        canonical_json({key: item for key, item in value.items() if key != "record_sha256"})
    ).hexdigest()
    return value


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


@pytest.mark.parametrize("field", ["candidate_receipt_sha256", "execution_receipt_sha256"])
@pytest.mark.parametrize("receipt", [None, digest(99)])
def test_verifier_must_bind_the_exact_candidate_and_execution_receipts(field, receipt):
    source_episode = episode()
    source_episode = replace(
        source_episode, verifier=replace(source_episode.verifier, **{field: receipt})
    )
    source = authority(source_episode=source_episode)
    governance = MemoryGovernanceAuthority()
    observed = governance.observe(
        source, observation_receipt_sha256=source.source_receipt_sha256, actor_fingerprint=ACTOR
    )

    with pytest.raises(RSILearningError, match="rsi_memory_verifier_receipt_mismatch"):
        governance.verify(
            observed,
            source_episode=source_episode,
            transition_receipt_sha256=digest(11),
            actor_fingerprint=ACTOR,
        )
    assert governance.get(source.memory_id) == observed


@pytest.mark.parametrize(
    ("baseline", "challenger"),
    [
        ("baseline_practice_receipt_sha256", "challenger_practice_receipt_sha256"),
        ("baseline_holdout_receipt_sha256", "challenger_holdout_receipt_sha256"),
        ("baseline_holdout_receipt_sha256", "baseline_practice_receipt_sha256"),
        ("baseline_holdout_receipt_sha256", "challenger_practice_receipt_sha256"),
        ("baseline_practice_receipt_sha256", "challenger_holdout_receipt_sha256"),
        ("challenger_practice_receipt_sha256", "challenger_holdout_receipt_sha256"),
    ],
)
def test_promotion_comparisons_cannot_reuse_a_receipt(baseline, challenger):
    evidence = gate(authority())
    with pytest.raises(RSILearningError, match="rsi_memory_gate_comparison_receipt_reused"):
        replace(evidence, **{baseline: getattr(evidence, challenger)})


@pytest.mark.parametrize("state", ["approved", "active", "deprecated", "revoked", "quarantined"])
@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"compatibility_fingerprint": digest(99)}, "rsi_memory_gate_compatibility_mismatch"),
        ({"parent_snapshot_sha256": digest(99)}, "rsi_memory_gate_parent_snapshot_mismatch"),
        (
            {
                "challenger_practice_receipt_sha256": digest(90),
                "practice_pass_receipts": (digest(90), digest(91)),
            },
            "rsi_memory_gate_source_receipt_unbound",
        ),
        ({"challenger_practice_score": 9}, "rsi_memory_gate_regression"),
        ({"challenger_holdout_score": 9}, "rsi_memory_gate_regression"),
        ({"holdout_failure_receipts": (digest(80),)}, "rsi_memory_gate_regression"),
    ],
)
def test_reconstructed_record_rechecks_gate_bindings_and_regression(state, changes, error):
    record = promotion_record(state)
    with pytest.raises(RSILearningError, match=error):
        replace(record, gate=replace(record.gate, **changes))


@pytest.mark.parametrize("state", ["active", "deprecated", "revoked", "quarantined"])
@pytest.mark.parametrize("incomplete", ["single_practice", "holdout_tie"])
def test_reconstructed_active_history_requires_activation_evidence(state, incomplete):
    record = promotion_record(state)
    changes = (
        {"practice_pass_receipts": (record.authority.source_receipt_sha256,)}
        if incomplete == "single_practice"
        else {"challenger_holdout_score": record.gate.baseline_holdout_score}
    )
    with pytest.raises(RSILearningError, match="rsi_memory_activation_evidence_insufficient"):
        replace(record, gate=replace(record.gate, **changes))


@pytest.mark.parametrize("state", ["revoked", "quarantined"])
def test_reconstructed_terminal_history_cannot_drop_promotion_evidence(state):
    record = promotion_record(state)
    with pytest.raises(RSILearningError, match="rsi_memory_gate_missing"):
        replace(record, gate=None)
    with pytest.raises(RSILearningError, match="rsi_memory_verifier_receipt_sha256_invalid"):
        replace(record, verifier_receipt_sha256=None, verifier_fingerprint=None)


@pytest.mark.parametrize("pending", ["single_practice", "holdout_tie"])
def test_approved_pending_record_can_be_deprecated_before_activation(pending):
    governance = MemoryGovernanceAuthority()
    source = authority()
    shadow = candidate_in_shadow(governance, source)
    evidence = (
        gate(source, practice_count=1)
        if pending == "single_practice"
        else gate(source, challenger_holdout_score=10)
    )
    approved = governance.approve(
        shadow, evidence, transition_receipt_sha256=digest(14), actor_fingerprint=ACTOR
    )
    deprecated = governance.deprecate(
        approved, transition_receipt_sha256=digest(16), actor_fingerprint=ACTOR
    )

    assert replace(deprecated) == deprecated
    assert not deprecated.gate.ready_for_activation
    assert "active" not in [receipt.state for receipt in deprecated.receipts]


@pytest.mark.parametrize(
    "other_scope",
    [
        MemoryScope("other-scope", "sorting", "stable-partition"),
        MemoryScope("problem-family:sorting", "other-family", "stable-partition"),
        MemoryScope("problem-family:sorting", "sorting", "other-conflict"),
    ],
)
def test_active_memories_in_different_complete_scopes_do_not_conflict(other_scope):
    governance = MemoryGovernanceAuthority()
    champion = activate(governance, authority("champion"))
    other_source = replace(authority("other"), scope=other_scope)
    other = activate(governance, other_source)

    assert governance.retrieve(scope=scope(), compatibility=compatibility()) == (champion,)
    assert governance.retrieve(scope=other_scope, compatibility=compatibility()) == (other,)


@pytest.mark.parametrize(
    "state",
    [
        "observed",
        "verified",
        "candidate",
        "shadow",
        "approved",
        "active",
        "deprecated",
        "revoked",
        "quarantined",
    ],
)
def test_promotion_records_round_trip_and_restore_every_lifecycle_state(state):
    history = promotion_history(state)
    parsed = tuple(MemoryPromotionRecord.from_dict(record.to_dict()) for record in history)
    restored = MemoryGovernanceAuthority.from_history(parsed)

    assert parsed == history
    assert restored.get("memory-1") == history[-1]
    expected = (history[-1],) if state == "active" else ()
    assert restored.retrieve(scope=scope(), compatibility=compatibility()) == expected


@pytest.mark.parametrize("value", [None, [], (), "record", True])
def test_promotion_wire_requires_an_object(value):
    with pytest.raises(RSILearningError, match="rsi_memory_governance_record_invalid"):
        MemoryPromotionRecord.from_dict(value)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("authority",),
        ("authority", "scope"),
        ("authority", "compatibility"),
        ("receipts", 0),
        ("gate",),
    ],
)
@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_promotion_wire_rejects_unknown_and_missing_fields_at_each_level(path, mutation):
    value = promotion_record("active").to_dict()
    node = value
    for key in path:
        node = node[key]
    if mutation == "unknown":
        node["unexpected"] = "ignored-by-old-parser"
    else:
        del node[next(iter(node))]

    with pytest.raises(RSILearningError, match="rsi_memory_governance_record_invalid"):
        MemoryPromotionRecord.from_dict(value)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("protocol", "wrong"), ("schema_version", 1), ("schema_version", True), ("kind", "wrong")],
)
def test_promotion_wire_rejects_protocol_drift(field, invalid):
    value = promotion_record("active").to_dict()
    value[field] = invalid

    with pytest.raises(RSILearningError, match="rsi_memory_governance_protocol_invalid"):
        MemoryPromotionRecord.from_dict(rehash_wire_record(value))


@pytest.mark.parametrize(
    "field",
    ["receipts", "practice_pass_receipts", "holdout_pass_receipts", "holdout_failure_receipts"],
)
@pytest.mark.parametrize("invalid", [None, (), {}, "receipts", True])
def test_promotion_wire_requires_json_arrays(field, invalid):
    value = promotion_record("active").to_dict()
    node = value if field == "receipts" else value["gate"]
    node[field] = invalid
    error = (
        "rsi_memory_lifecycle_receipts_invalid"
        if field == "receipts"
        else f"rsi_memory_{field}_invalid"
    )

    with pytest.raises(RSILearningError, match=error):
        MemoryPromotionRecord.from_dict(value)


@pytest.mark.parametrize(
    "field",
    [
        "baseline_practice_score",
        "challenger_practice_score",
        "baseline_holdout_score",
        "challenger_holdout_score",
    ],
)
@pytest.mark.parametrize("invalid", [True, False, None, 10.0, "10"])
def test_promotion_wire_rejects_noninteger_scores(field, invalid):
    value = promotion_record("active").to_dict()
    value["gate"][field] = invalid

    with pytest.raises(RSILearningError, match=f"rsi_memory_{field}_invalid"):
        MemoryPromotionRecord.from_dict(rehash_wire_record(value))


def test_promotion_wire_rejects_digest_drift_and_bounded_payload_overflow():
    value = promotion_record("active").to_dict()
    value["authority"]["content_sha256"] = digest(99)
    with pytest.raises(RSILearningError, match="rsi_memory_governance_record_digest_mismatch"):
        MemoryPromotionRecord.from_dict(value)

    value = promotion_record("active").to_dict()
    value["authority"]["scope"]["problem_family"] = "x" * (128 * 1024)
    with pytest.raises(RSILearningError, match="rsi_memory_governance_record_invalid"):
        MemoryPromotionRecord.from_dict(value)


@pytest.mark.parametrize(
    ("field", "invalid", "error"),
    [
        ("compatibility_fingerprint", digest(99), "rsi_memory_gate_compatibility_mismatch"),
        ("parent_snapshot_sha256", digest(99), "rsi_memory_gate_parent_snapshot_mismatch"),
        ("challenger_practice_score", 9, "rsi_memory_gate_regression"),
        ("challenger_holdout_score", 10, "rsi_memory_activation_evidence_insufficient"),
        ("practice_pass_receipts", [digest(7)], "rsi_memory_activation_evidence_insufficient"),
        ("holdout_failure_receipts", [digest(80)], "rsi_memory_gate_regression"),
    ],
)
def test_recomputing_record_digest_cannot_bypass_promotion_gates(field, invalid, error):
    value = promotion_record("active").to_dict()
    value["gate"][field] = invalid

    with pytest.raises(RSILearningError, match=error):
        MemoryPromotionRecord.from_dict(rehash_wire_record(value))


def test_promotion_wire_rejects_early_verifier_and_gate_evidence():
    value = promotion_history("observed")[-1].to_dict()
    value["verifier_receipt_sha256"] = digest(10)
    value["verifier_fingerprint"] = VERIFIER
    with pytest.raises(RSILearningError, match="rsi_memory_verifier_evidence_invalid"):
        MemoryPromotionRecord.from_dict(rehash_wire_record(value))

    value = promotion_history("shadow")[-1].to_dict()
    value["gate"] = gate(authority()).to_dict()
    with pytest.raises(RSILearningError, match="rsi_memory_gate_invalid"):
        MemoryPromotionRecord.from_dict(rehash_wire_record(value))


def test_restored_interleaved_histories_can_continue_without_accepting_stale_records():
    first = promotion_history("verified")
    second = promotion_history("verified", source=authority("memory-2"))
    history = tuple(record for pair in zip(first, second) for record in pair)
    restored = MemoryGovernanceAuthority.from_history(iter(history))
    advanced = restored.nominate_candidate(
        first[-1], transition_receipt_sha256=digest(99), actor_fingerprint=ACTOR
    )

    assert restored.get("memory-1") == advanced
    assert restored.get("memory-2") == second[-1]
    with pytest.raises(RSILearningError, match="rsi_memory_stale_record"):
        restored.nominate_candidate(
            first[-1], transition_receipt_sha256=digest(98), actor_fingerprint=ACTOR
        )


@pytest.mark.parametrize("value", [None, True, "history", b"history", {}])
def test_history_requires_an_iterable_of_typed_records(value):
    with pytest.raises(RSILearningError, match="rsi_memory_governance_history_invalid"):
        MemoryGovernanceAuthority.from_history(value)


def test_history_rejects_raw_wire_dicts_and_accepts_empty_history():
    assert MemoryGovernanceAuthority.from_history([]).get("unknown") is None
    with pytest.raises(RSILearningError, match="rsi_memory_promotion_record_invalid"):
        MemoryGovernanceAuthority.from_history([promotion_record("active").to_dict()])


@pytest.mark.parametrize(
    "state",
    [
        "verified",
        "candidate",
        "shadow",
        "approved",
        "active",
        "deprecated",
        "revoked",
        "quarantined",
    ],
)
def test_history_cannot_restore_only_a_nonobserved_head(state):
    with pytest.raises(RSILearningError, match="rsi_memory_governance_history_incomplete"):
        MemoryGovernanceAuthority.from_history([promotion_history(state)[-1]])


@pytest.mark.parametrize("index", range(1, 5))
def test_history_rejects_missing_intermediate_revisions(index):
    history = promotion_history()
    with pytest.raises(RSILearningError, match="rsi_memory_governance_history_chain_mismatch"):
        MemoryGovernanceAuthority.from_history(history[:index] + history[index + 1 :])


@pytest.mark.parametrize(
    "mutation", ["duplicate", "reordered", "previous_digest", "receipt_prefix"]
)
def test_history_rejects_broken_chains_even_when_individual_records_parse(mutation):
    history = list(promotion_history())
    if mutation == "duplicate":
        history.insert(2, history[1])
    elif mutation == "reordered":
        history[1], history[2] = history[2], history[1]
    elif mutation == "previous_digest":
        history[2] = replace(history[2], previous_record_sha256=digest(99))
    else:
        record = history[2]
        receipt = replace(record.receipts[0], reason_code="changed_observation_reason")
        history[2] = replace(record, receipts=(receipt,) + record.receipts[1:])
    assert all(MemoryPromotionRecord.from_dict(record.to_dict()) == record for record in history)

    with pytest.raises(RSILearningError, match="rsi_memory_governance_history_chain_mismatch"):
        MemoryGovernanceAuthority.from_history(history)


@pytest.mark.parametrize(
    "mutation", ["authority", "verifier_receipt", "verifier_fingerprint", "gate"]
)
def test_history_evidence_and_authority_cannot_be_rewritten_after_introduction(mutation):
    history = list(promotion_history())
    if mutation == "authority":
        history[2] = replace(
            history[2], authority=replace(history[2].authority, content_sha256=digest(99))
        )
        error = "rsi_memory_governance_history_authority_mismatch"
    elif mutation == "gate":
        history[-1] = replace(
            history[-1], gate=replace(history[-1].gate, challenger_holdout_score=12)
        )
        error = "rsi_memory_governance_history_gate_mismatch"
    else:
        field = "verifier_receipt_sha256" if mutation == "verifier_receipt" else mutation
        history[2] = replace(history[2], **{field: digest(99)})
        error = "rsi_memory_governance_history_verifier_mismatch"
    assert all(MemoryPromotionRecord.from_dict(record.to_dict()) == record for record in history)

    with pytest.raises(RSILearningError, match=error):
        MemoryGovernanceAuthority.from_history(history)


@pytest.mark.parametrize("second_state", ["active", "revoked", "quarantined"])
def test_history_rejects_conflicting_activation_even_if_later_revoked(second_state):
    first = promotion_history(source=authority("champion"))
    second = promotion_history(second_state, source=authority("challenger"))
    with pytest.raises(RSILearningError, match="rsi_memory_active_conflict"):
        MemoryGovernanceAuthority.from_history(first + second)


def test_history_accepts_replacement_after_retained_deprecation():
    first = promotion_history("deprecated", source=authority("champion"))
    second = promotion_history(source=authority("challenger"))
    restored = MemoryGovernanceAuthority.from_history(first + second)
    assert restored.retrieve(scope=scope(), compatibility=compatibility()) == (second[-1],)


def test_history_keeps_revoked_and_quarantined_memories_excluded():
    first = promotion_history("revoked", source=authority("first"))
    second = promotion_history("quarantined", source=authority("second"))
    restored = MemoryGovernanceAuthority.from_history(first + second)
    assert restored.retrieve(scope=scope(), compatibility=compatibility()) == ()


@pytest.mark.parametrize(
    "other_scope",
    [
        MemoryScope("other-scope", "sorting", "stable-partition"),
        MemoryScope("problem-family:sorting", "other-family", "stable-partition"),
        MemoryScope("problem-family:sorting", "sorting", "other-conflict"),
    ],
)
def test_history_restores_active_memories_in_distinct_complete_scopes(other_scope):
    first = promotion_history(source=authority("first"))
    second = promotion_history(source=replace(authority("second"), scope=other_scope))
    restored = MemoryGovernanceAuthority.from_history(first + second)
    assert restored.retrieve(scope=scope(), compatibility=compatibility()) == (first[-1],)
    assert restored.retrieve(scope=other_scope, compatibility=compatibility()) == (second[-1],)


def test_history_does_not_mutate_source_wire_records():
    wires = [record.to_dict() for record in promotion_history()]
    original = deepcopy(wires)
    restored = MemoryGovernanceAuthority.from_history(
        MemoryPromotionRecord.from_dict(value) for value in wires
    )
    assert restored.get("memory-1").to_dict() == wires[-1]
    assert wires == original
