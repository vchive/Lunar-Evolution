import hashlib
import json

import pytest

from lunar_evolution import (
    EMPTY_MEMORY_SNAPSHOT,
    EMPTY_MEMORY_SNAPSHOT_SHA256,
    ReadOnlyMemorySnapshot,
    RSILearningError,
    RSIMemoryItem,
    RSIMemorySnapshot,
    RSIPracticeEpisode,
    RSITraceEvent,
    RSIVerifierCheck,
    RSIVerifierDecision,
    load_episode_record,
    load_memory_snapshot,
)

HEX = "a" * 64


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def memory_item(memory_id: str = "memory-1") -> RSIMemoryItem:
    return RSIMemoryItem(
        memory_id=memory_id,
        problem_family="sorting",
        trigger="duplicate-heavy input",
        strategy="use a stable partition before local search",
        expected_result="stable output on duplicate-heavy inputs",
        failure_boundary="does not apply when output order is unconstrained",
        compatible_contracts=(HEX,),
        compatible_solvers=("native", "openevolve"),
        verifier_outcome="pass",
        receipt_sha256=HEX,
        episode_id="episode-1",
    )


def test_snapshot_is_canonical_and_read_only():
    snapshot = RSIMemorySnapshot("snapshot-1", None, (memory_item(),))
    loaded = load_memory_snapshot(snapshot.to_bytes())

    assert loaded == snapshot
    assert loaded.digest() == hashlib.sha256(snapshot.to_bytes()).hexdigest()
    readonly = ReadOnlyMemorySnapshot(loaded)
    assert readonly.digest == loaded.digest()
    assert readonly.get("memory-1") == loaded.items[0]
    with pytest.raises(AttributeError):
        readonly.items = ()
    with pytest.raises(AttributeError):
        readonly._snapshot = RSIMemorySnapshot("snapshot-2", None, ())
    with pytest.raises(TypeError):
        readonly._by_id["other"] = loaded.items[0]


def test_memory_exposes_causal_projection_and_public_trace_events_roundtrip():
    item = memory_item()
    assert item.condition == item.trigger
    assert item.action == item.strategy
    assert item.observed_result == item.expected_result
    assert item.applicability == item.failure_boundary

    event = RSITraceEvent(0, "action", "click", HEX, HEX)
    episode = base_episode().transition("running", request_sha256=HEX).transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
        trace_events=(event,),
        actor_fingerprint=HEX,
        solver_fingerprint=HEX,
        candidate_source_sha256=HEX,
        dependency_sha256=HEX,
    )
    assert load_episode_record(episode.to_bytes()).trace_events == (event,)


def test_snapshot_rejects_unapproved_memory():
    item = memory_item()
    payload = item.to_dict()
    payload["status"] = "rejected"
    payload["compatible_contracts"] = tuple(item.compatible_contracts)
    payload["compatible_solvers"] = tuple(item.compatible_solvers)
    rejected = RSIMemoryItem(**payload)
    with pytest.raises(RSILearningError) as error:
        RSIMemorySnapshot("snapshot-1", None, (rejected,))
    assert error.value.code == "rsi_memory_snapshot_unapproved"


def test_snapshot_rejects_noncanonical_bytes():
    snapshot = RSIMemorySnapshot("snapshot-1", None, (memory_item(),))
    content = b" " + snapshot.to_bytes()
    with pytest.raises(RSILearningError) as error:
        load_memory_snapshot(content)
    assert error.value.code == "rsi_memory_snapshot_noncanonical"


def test_legacy_snapshot_roundtrips_without_new_causal_fields():
    current = RSIMemorySnapshot("snapshot-legacy", None, (memory_item(),)).to_dict()
    legacy_item = current["items"][0]
    for name in ("condition", "action", "observed_result", "applicability"):
        legacy_item.pop(name)
    content = canonical_json(current)

    loaded = load_memory_snapshot(content)

    assert loaded.to_bytes() == content
    assert loaded.digest() == hashlib.sha256(content).hexdigest()
    assert loaded.items[0].condition == loaded.items[0].trigger


def test_snapshot_rejects_mutable_item_containers_and_uppercase_digests():
    item = memory_item()
    with pytest.raises(RSILearningError) as mutable_items:
        RSIMemorySnapshot("snapshot-1", None, [item])
    assert mutable_items.value.code == "rsi_memory_snapshot_invalid"

    with pytest.raises(RSILearningError) as uppercase_digest:
        RSIMemorySnapshot("snapshot-2", "A" * 64, ())
    assert uppercase_digest.value.code == "rsi_parent_snapshot_sha256_invalid"


def test_completed_episode_must_bind_verifier_to_same_episode():
    decision = RSIVerifierDecision(
        "episode-1", "pass", HEX, "verified transfer", HEX,
        (RSIVerifierCheck("official_evaluator", "pass", HEX),),
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        evidence_sha256=HEX,
    )
    episode = RSIPracticeEpisode(
        episode_id="episode-1",
        run_id="run-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256,
        solver_id="native",
        status="completed",
        verifier=decision,
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
    )
    assert episode.to_dict()["verifier"]["outcome"] == "pass"

    with pytest.raises(RSILearningError) as error:
        RSIPracticeEpisode(
            episode_id="episode-1",
            run_id="run-1",
            contract_sha256=HEX,
            evaluator_sha256=HEX,
            environment_sha256=HEX,
            memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256,
            solver_id="native",
            status="unknown",
            verifier=decision,
            candidate_receipt_sha256=HEX,
            execution_receipt_sha256=HEX,
            official_evaluation_receipt_sha256=HEX,
        )
    assert error.value.code == "rsi_incomplete_episode_verified"


def test_empty_snapshot_is_explicit_and_transfer_receipt_is_frozen():
    assert EMPTY_MEMORY_SNAPSHOT.items == ()
    assert EMPTY_MEMORY_SNAPSHOT.digest() == EMPTY_MEMORY_SNAPSHOT_SHA256


def base_episode(status="planned") -> RSIPracticeEpisode:
    return RSIPracticeEpisode(
        episode_id="episode-1",
        run_id="run-1",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256,
        solver_id="native",
        status=status,
    )


def test_episode_record_state_is_fail_closed():
    with pytest.raises(RSILearningError) as planned:
        base_episode().transition("running", request_sha256=HEX)
        RSIPracticeEpisode(
            episode_id="episode-1",
            run_id="run-1",
            contract_sha256=HEX,
            evaluator_sha256=HEX,
            environment_sha256=HEX,
            memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT_SHA256,
            solver_id="native",
            status="planned",
            request_sha256=HEX,
        ).to_bytes()
    assert planned.value.code == "rsi_planned_evidence_invalid"

    running = base_episode().transition("running", request_sha256=HEX)
    with pytest.raises(RSILearningError) as running_error:
        running.transition("completed", trace_digest=HEX)
    assert running_error.value.code in {"rsi_running_evidence_invalid", "rsi_completed_evidence_missing"}

    with pytest.raises(RSILearningError) as terminal:
        base_episode().transition("running", request_sha256=HEX).transition("failed")
    assert terminal.value.code == "rsi_terminal_reason_missing"


def test_episode_transition_keeps_request_and_record_lineage():
    running = base_episode().transition("running", request_sha256=HEX)
    completed = running.transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    assert completed.previous_record_sha256 == running.digest()
    assert completed.record_sha256 == completed.digest()
    with pytest.raises(RSILearningError) as changed:
        running.transition("completed", request_sha256="b" * 64)
    assert changed.value.code == "rsi_episode_request_changed"


def test_episode_record_roundtrip_and_tamper_detection():
    completed = base_episode().transition("running", request_sha256=HEX).transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    loaded = load_episode_record(completed.to_bytes())
    assert loaded == completed

    payload = completed.to_record_dict()
    payload["status"] = "failed"
    with pytest.raises(RSILearningError) as tampered:
        load_episode_record(payload)
    assert tampered.value.code in {"rsi_terminal_reason_missing", "rsi_episode_record_digest_mismatch"}

    with pytest.raises(RSILearningError) as noncanonical:
        load_episode_record(b" " + completed.to_bytes())
    assert noncanonical.value.code == "rsi_episode_record_noncanonical"


def test_legacy_episode_roundtrips_without_new_trace_fields():
    completed = base_episode().transition("running", request_sha256=HEX).transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    legacy = completed.to_record_dict()
    for name in (
        "actor_fingerprint", "solver_fingerprint", "candidate_source_sha256",
        "dependency_sha256", "trace_events",
    ):
        legacy.pop(name)
    legacy["record_sha256"] = hashlib.sha256(canonical_json({
        key: value for key, value in legacy.items() if key != "record_sha256"
    })).hexdigest()
    content = canonical_json(legacy)

    loaded = load_episode_record(content)

    assert loaded.to_bytes() == content
    assert loaded.record_sha256 == legacy["record_sha256"]
    assert loaded.actor_fingerprint is None


def test_pass_verifier_must_bind_official_evaluator_receipt():
    decision = RSIVerifierDecision(
        "episode-1", "pass", HEX, "verified", HEX,
        (RSIVerifierCheck("official_evaluator", "pass", HEX),),
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        evidence_sha256=HEX,
    )
    completed = base_episode().transition("running", request_sha256=HEX).transition(
        "completed",
        candidate_receipt_sha256=HEX,
        execution_receipt_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        trace_digest=HEX,
    )
    verified = completed.attach_verifier(decision)
    assert load_episode_record(verified.to_bytes()) == verified

    mismatched = decision.checks[0]
    bad_decision = RSIVerifierDecision(
        "episode-1", "pass", HEX, "verified", HEX,
        (RSIVerifierCheck("official_evaluator", "pass", "b" * 64),),
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        official_evaluation_receipt_sha256=HEX,
        evidence_sha256=HEX,
    )
    del mismatched
    with pytest.raises(RSILearningError) as mismatch:
        completed.attach_verifier(bad_decision)
    assert mismatch.value.code == "rsi_verifier_receipt_mismatch"
