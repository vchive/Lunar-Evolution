"""Durable candidate recovery and the boundary before trusted holdout promotion."""

import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest

from lunar_evolution.rsi_controller import PracticeEpisodeRunner, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest
from lunar_evolution.rsi_governance_store import RSIMemoryGovernanceLedger
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
)
from lunar_evolution.rsi_memory_governance import MemoryScope, PromotionGate
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
ACTOR = "b" * 64
PINS = {
    "contract_sha256": HEX,
    "evaluator_sha256": HEX,
    "environment_sha256": HEX,
    "solver_id": "mock",
}


def material(ledger, *, episode_id="practice"):
    request = SolverRequest.build(
        episode_id=episode_id, memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(), **PINS
    )
    planned = PracticeEpisode(
        episode_id, "run", HEX, HEX, HEX, EMPTY_MEMORY_SNAPSHOT.digest(), "mock", "planned"
    )
    execution = PracticeEpisodeRunner(DeterministicMockSolver(), ledger=ledger).run(
        planned, request
    )
    memory = MemoryItem(
        "memory-" + episode_id,
        "sorting",
        "input is reversed",
        "sort input",
        "sorted",
        "integers only",
        (HEX,),
        ("mock",),
        "pass",
        execution.verifier.receipt_sha256,
        episode_id,
    )
    scope = MemoryScope("sorting-domain", "sorting", "sort")
    return execution.episode, memory, scope


def nominate(store, episode, memory, scope):
    return store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)


def test_nomination_restores_source_bound_candidate_without_authorizing_memory(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = nominate(store, episode, memory, scope)
    restarted = RSIMemoryGovernanceLedger(RSILedger(ledger.database))

    assert [record.state for record in restarted.history(memory.memory_id)] == [
        "observed",
        "verified",
        "candidate",
    ]
    assert restarted.restore().get(memory.memory_id) == candidate
    assert (
        restarted.restore().retrieve(scope=scope, compatibility=candidate.authority.compatibility)
        == ()
    )
    assert nominate(restarted, episode, memory, scope) == candidate
    assert len(restarted.history(memory.memory_id)) == 3


@pytest.mark.parametrize("state", ["observed", "verified"])
def test_interrupted_nomination_only_appends_missing_transitions(tmp_path, monkeypatch, state):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    original = store.append

    def interrupted(record, **kwargs):
        retained = original(record, **kwargs)
        if record.state == state:
            raise RuntimeError("nomination interrupted")
        return retained

    monkeypatch.setattr(store, "append", interrupted)
    with pytest.raises(RuntimeError, match="nomination interrupted"):
        nominate(store, episode, memory, scope)
    assert len(store.history(memory.memory_id)) == (1 if state == "observed" else 2)
    restored = RSIMemoryGovernanceLedger(RSILedger(ledger.database))
    assert nominate(restored, episode, memory, scope).state == "candidate"
    assert len(restored.history(memory.memory_id)) == 3


def test_compare_and_swap_prevents_stale_shadow_and_exact_repetition_is_idempotent(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = nominate(store, episode, memory, scope)
    left, right = store.restore(), store.restore()
    shadow = left.start_shadow(
        candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR
    )
    store.append(shadow, memory=memory, expected_record_sha256=candidate.digest())
    assert store.append(shadow, memory=memory, expected_record_sha256=candidate.digest()) == shadow
    stale = right.start_shadow(
        candidate, transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR
    )
    with pytest.raises(RSILearningError, match="rsi_memory_governance_parent_conflict"):
        store.append(stale, memory=memory, expected_record_sha256=candidate.digest())
    assert store.restore().get(memory.memory_id) == shadow


def test_changed_nomination_cannot_replace_content_or_revive_quarantined_memory(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = nominate(store, episode, memory, scope)
    with pytest.raises(RSILearningError, match="rsi_memory_candidate_identity_drift"):
        nominate(store, episode, replace(memory, strategy="changed"), scope)
    governance = store.restore()
    quarantined = governance.quarantine(
        candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR
    )
    store.append(quarantined, memory=memory, expected_record_sha256=candidate.digest())
    assert nominate(store, episode, memory, scope) == quarantined
    assert (
        store.restore().retrieve(scope=scope, compatibility=candidate.authority.compatibility) == ()
    )


def test_observed_record_binds_memory_receipt_to_retained_source_verifier(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    source_episode, memory, scope = material(ledger)
    wrong_memory = replace(memory, receipt_sha256="f" * 64)

    with pytest.raises(RSILearningError, match="rsi_memory_source_verifier_mismatch"):
        store.nominate(
            episode=source_episode,
            memory=wrong_memory,
            scope=scope,
            actor_fingerprint=ACTOR,
        )
    assert RSIMemoryGovernanceLedger.inspect_records(ledger) == ()


def test_read_only_inspection_does_not_initialize_governance_journal(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")

    assert RSIMemoryGovernanceLedger.inspect_records(ledger) == ()
    with sqlite3.connect(ledger.database) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rsi_memory_governance'"
            ).fetchone()
            is None
        )
    with pytest.raises(RSILearningError, match="rsi_memory_governance_journal_missing"):
        RSIMemoryGovernanceLedger.inspect_records(ledger, require_journal=True)


@pytest.mark.parametrize("tamper", ["delete_transition", "content", "record_digest", "source"])
def test_recovery_rejects_journal_and_source_tampering(tmp_path, tamper):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    nominate(store, episode, memory, scope)
    with sqlite3.connect(ledger.database) as connection:
        if tamper == "delete_transition":
            connection.execute("DELETE FROM rsi_memory_governance WHERE revision = 1")
        elif tamper == "source":
            connection.execute(
                "DELETE FROM rsi_records WHERE logical_id = ?", (episode.episode_id,)
            )
        elif tamper == "record_digest":
            connection.execute(
                "UPDATE rsi_memory_governance SET record_sha256 = ? WHERE revision = 2", ("f" * 64,)
            )
        else:
            row = connection.execute(
                "SELECT payload FROM rsi_memory_governance WHERE revision = 2"
            ).fetchone()
            value = json.loads(row[0])
            value["memory"]["strategy"] = "replaced"
            connection.execute(
                "UPDATE rsi_memory_governance SET payload = ? WHERE revision = 2",
                (json.dumps(value),),
            )
    with pytest.raises(RSILearningError):
        RSIMemoryGovernanceLedger(RSILedger(ledger.database)).restore()


def test_even_structurally_valid_gate_cannot_authorize_durable_activation(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = nominate(store, episode, memory, scope)
    governance = store.restore()
    shadow = governance.start_shadow(
        candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR
    )
    store.append(shadow, memory=memory, expected_record_sha256=candidate.digest())
    gate = PromotionGate(
        candidate.authority.compatibility.digest(),
        EMPTY_MEMORY_SNAPSHOT.digest(),
        "1" * 64,
        candidate.authority.source_receipt_sha256,
        "2" * 64,
        "3" * 64,
        10,
        11,
        10,
        11,
        (candidate.authority.source_receipt_sha256, "4" * 64),
        ("3" * 64,),
    )
    approved = governance.approve(
        shadow, gate, transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR
    )
    with pytest.raises(RSILearningError, match="rsi_memory_trusted_promotion_unavailable"):
        store.append(approved, memory=memory, expected_record_sha256=shadow.digest())
    assert store.restore().get(memory.memory_id).state == "shadow"


class Gateway:
    def __init__(self):
        self.requests = []

    def fingerprint(self):
        return hashlib.sha256(b"governed-fixture").hexdigest()

    def run(self, request):
        self.requests.append(request)
        return DeterministicMockSolver().run(request)


def judge_after_practice(execution):
    return execution.episode.wave > 0, "needs practice"


def controller(ledger, gateway, *, governed=True):
    return RSILearningController(
        gateway,
        ledger=ledger,
        target_judge=judge_after_practice,
        memory_governance=RSIMemoryGovernanceLedger(ledger) if governed else None,
    )


def test_governed_controller_persists_candidates_and_reuses_them_without_solver_replay(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    gateway = Gateway()
    instance = controller(ledger, gateway)
    result = instance.run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    assert result.status == "completed"
    assert result.memory_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert {request.memory_snapshot_sha256 for request in gateway.requests} == {
        EMPTY_MEMORY_SNAPSHOT.digest()
    }
    candidate = instance.memory_governance.restore().get("memory-governed-practice-0-0")
    assert candidate.state == "candidate"
    second_gateway = Gateway()
    restored = controller(RSILedger(ledger.database), second_gateway)
    assert restored.resume(run_id="governed") == result
    assert second_gateway.requests == []
    assert len(restored.memory_governance.history(candidate.authority.memory_id)) == 3


def test_governed_checkpoint_pins_candidate_record_and_requires_journal_on_resume(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    gateway = Gateway()
    instance = controller(ledger, gateway)
    result = instance.run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    assert result.status == "completed"
    checkpoint = ledger.controller_checkpoint("governed")
    assert checkpoint is not None
    state = checkpoint[1]
    candidate_id = "governed-practice-0-0"
    candidate = instance.memory_governance.restore().get("memory-" + candidate_id)
    assert state["candidate_record_digests"][candidate_id] == candidate.digest()

    with sqlite3.connect(ledger.database) as connection:
        connection.execute("DELETE FROM rsi_memory_governance")
    with pytest.raises(RSILearningError, match="rsi_memory_candidate_evidence_missing"):
        controller(RSILedger(ledger.database), Gateway()).resume(run_id="governed")
    assert RSIMemoryGovernanceLedger.inspect_records(ledger) == ()


@pytest.mark.parametrize("remaining", [1, 2])
def test_committed_candidate_history_cannot_be_silently_completed_during_resume(tmp_path, remaining):
    ledger = RSILedger(tmp_path / "rsi.db")
    controller(ledger, Gateway()).run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    with sqlite3.connect(ledger.database) as connection:
        connection.execute("DELETE FROM rsi_memory_governance WHERE revision >= ?", (remaining,))
    restored = controller(RSILedger(ledger.database), Gateway())
    with pytest.raises(RSILearningError, match="rsi_memory_candidate_evidence_missing"):
        restored.resume(run_id="governed")
    assert len(RSIMemoryGovernanceLedger.inspect_records(ledger)) == remaining


@pytest.mark.parametrize("mutation", ["remove_map", "wrong_digest", "missing_digest", "extra_digest"])
def test_candidate_checkpoint_requires_exact_committed_episode_digests(tmp_path, mutation):
    ledger = RSILedger(tmp_path / "rsi.db")
    controller(ledger, Gateway()).run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    version, state = ledger.controller_checkpoint("governed")
    if mutation == "remove_map":
        del state["candidate_record_digests"]
    elif mutation == "wrong_digest":
        state["candidate_record_digests"]["governed-practice-0-0"] = "f" * 64
    elif mutation == "missing_digest":
        state["candidate_record_digests"].clear()
    else:
        state["candidate_record_digests"]["uncommitted-practice"] = "f" * 64
    with ledger.controller_lock("governed"):
        ledger.write_controller_checkpoint("governed", state, expected_sha256=version)
    expected = "rsi_memory_candidate_evidence_missing" if mutation == "wrong_digest" else "rsi_memory_candidate_checkpoint_invalid"
    with pytest.raises(RSILearningError, match=expected):
        controller(RSILedger(ledger.database), Gateway()).resume(run_id="governed")


@pytest.mark.parametrize("field", ["initial_memory_snapshot", "memory_snapshot"])
def test_candidate_only_resume_rejects_nonempty_checkpoint_snapshots(tmp_path, field):
    ledger = RSILedger(tmp_path / "rsi.db")
    controller(ledger, Gateway()).run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    _episode, memory, _scope = material(ledger, episode_id="unrelated-source")
    version, state = ledger.controller_checkpoint("governed")
    state[field] = MemorySnapshot("injected", EMPTY_MEMORY_SNAPSHOT.digest(), (memory,)).to_dict()
    with ledger.controller_lock("governed"):
        ledger.write_controller_checkpoint("governed", state, expected_sha256=version)
    gateway = Gateway()
    with pytest.raises(RSILearningError, match="rsi_memory_trusted_promotion_unavailable"):
        controller(RSILedger(ledger.database), gateway).resume(run_id="governed")
    assert gateway.requests == []


@pytest.mark.parametrize("state", ["revoked", "quarantined"])
def test_controller_resume_preserves_later_candidate_terminal_state_without_writes(tmp_path, state, monkeypatch):
    ledger = RSILedger(tmp_path / "rsi.db")
    instance = controller(ledger, Gateway())
    result = instance.run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    store = instance.memory_governance
    authority = store.restore()
    candidate = authority.get("memory-governed-practice-0-0")
    terminal = getattr(authority, "revoke" if state == "revoked" else "quarantine")(
        candidate, transition_receipt_sha256="e" * 64, actor_fingerprint=ACTOR
    )
    with sqlite3.connect(ledger.database) as connection:
        raw = connection.execute("SELECT payload FROM rsi_memory_governance WHERE revision = 2").fetchone()[0]
    memory = MemoryItem.from_dict(json.loads(raw)["memory"])
    store.append(terminal, memory=memory, expected_record_sha256=candidate.digest())
    records = store.inspect_records(ledger)

    def forbidden_nominate(*args, **kwargs):
        raise AssertionError("resume must only inspect committed candidates")

    restarted = controller(RSILedger(ledger.database), Gateway())
    monkeypatch.setattr(restarted.memory_governance, "nominate", forbidden_nominate)
    assert restarted.resume(run_id="governed") == result
    assert restarted.memory_governance.restore().get(candidate.authority.memory_id) == terminal
    assert restarted.memory_governance.inspect_records(ledger) == records


@pytest.mark.parametrize("interrupted_state", ["observed", "verified", "candidate"])
def test_controller_resumes_nomination_interrupted_before_commit_checkpoint(tmp_path, monkeypatch, interrupted_state):
    ledger = RSILedger(tmp_path / "rsi.db")
    instance = controller(ledger, Gateway())
    original = instance.memory_governance.append

    def interrupted(record, **kwargs):
        retained = original(record, **kwargs)
        if record.state == interrupted_state:
            raise RuntimeError("interrupted nomination before checkpoint")
        return retained

    monkeypatch.setattr(instance.memory_governance, "append", interrupted)
    with pytest.raises(RuntimeError, match="interrupted nomination before checkpoint"):
        instance.run_drs(run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2)
    checkpoint = ledger.controller_checkpoint("governed")[1]
    assert checkpoint["commits"] == []
    assert checkpoint["candidate_record_digests"] == {}
    gateway = Gateway()
    restored = controller(RSILedger(ledger.database), gateway)
    assert restored.resume(run_id="governed").status == "completed"
    assert [request.episode_id for request in gateway.requests] == ["governed-target-1"]
    history = restored.memory_governance.history("memory-governed-practice-0-0")
    assert [record.state for record in history] == ["observed", "verified", "candidate"]


def test_durable_run_cannot_switch_out_of_governed_policy(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    controller(ledger, Gateway()).run_drs(
        run_id="governed", **PINS, max_practice_rounds=1, max_target_attempts=2
    )
    with pytest.raises(RSILearningError, match="rsi_resume_memory_policy_drift"):
        controller(RSILedger(ledger.database), Gateway(), governed=False).resume(run_id="governed")


def test_governed_controller_rejects_an_unrelated_database(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    unrelated = RSIMemoryGovernanceLedger(RSILedger(tmp_path / "other.db"))
    with pytest.raises(RSILearningError, match="rsi_memory_governance_ledger_mismatch"):
        RSILearningController(DeterministicMockSolver(), ledger=ledger, memory_governance=unrelated)
