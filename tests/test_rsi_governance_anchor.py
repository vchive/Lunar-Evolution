"""High-water governance anchor rejects erased terminal transitions."""

import sqlite3

import pytest

from lunar_evolution.rsi_controller import PracticeEpisodeRunner
from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest
from lunar_evolution.rsi_governance_store import RSIMemoryGovernanceLedger
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    PracticeEpisode,
    RSILearningError,
)
from lunar_evolution.rsi_memory_governance import MemoryScope
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
ACTOR = "b" * 64
PINS = {
    "contract_sha256": HEX,
    "evaluator_sha256": HEX,
    "environment_sha256": HEX,
    "solver_id": "mock",
}


def material(ledger):
    request = SolverRequest.build(
        episode_id="anchor-practice", memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(), **PINS
    )
    planned = PracticeEpisode(
        "anchor-practice", "anchor-run", HEX, HEX, HEX,
        EMPTY_MEMORY_SNAPSHOT.digest(), "mock", "planned",
    )
    episode = PracticeEpisodeRunner(DeterministicMockSolver(), ledger=ledger).run(planned, request).episode
    memory = MemoryItem(
        "memory-anchor-practice", "sorting", "input is reversed", "sort input", "sorted",
        "integers only", (HEX,), ("mock",), "pass", episode.verifier.receipt_sha256,
        episode.episode_id,
    )
    return episode, memory, MemoryScope("sorting-domain", "sorting", "sort")


def test_anchor_advances_and_detects_erased_tail(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)

    anchor = store.checkpoint_anchor()
    assert anchor["position"] == 2
    assert anchor["record_sha256"]
    assert anchor["state"] == "candidate"
    store.validate_anchor(anchor)

    with sqlite3.connect(ledger.database) as connection:
        connection.execute("DELETE FROM rsi_memory_governance WHERE position = 2")
    with pytest.raises(RSILearningError, match="rsi_memory_governance_anchor_mismatch"):
        RSIMemoryGovernanceLedger(RSILedger(ledger.database)).restore()


def test_anchor_tampering_fails_closed(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)
    with sqlite3.connect(ledger.database) as connection:
        connection.execute(
            "UPDATE rsi_memory_governance_anchor SET position = position - 1 WHERE anchor_id = 1"
        )
    with pytest.raises(RSILearningError, match="rsi_memory_governance_anchor_mismatch"):
        store.restore()


def test_existing_unanchored_journal_is_not_silently_upgraded(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)
    with sqlite3.connect(ledger.database) as connection:
        connection.execute("DROP TABLE rsi_memory_governance_anchor")
    with pytest.raises(RSILearningError, match="rsi_memory_governance_anchor_missing"):
        RSIMemoryGovernanceLedger(RSILedger(ledger.database)).restore()

@pytest.mark.parametrize("state", ["revoked", "quarantined"])
def test_anchor_rejects_erased_terminal_transition(tmp_path, state):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = store.nominate(
        episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR,
    )
    authority = store.restore()
    terminal = getattr(authority, "revoke" if state == "revoked" else "quarantine")(
        candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR,
    )
    store.append(terminal, memory=memory, expected_record_sha256=candidate.digest())
    with sqlite3.connect(ledger.database) as connection:
        connection.execute("DELETE FROM rsi_memory_governance WHERE position = 3")
    with pytest.raises(RSILearningError, match="rsi_memory_governance_anchor_mismatch"):
        RSIMemoryGovernanceLedger(RSILedger(ledger.database)).restore()


def test_checkpoint_anchor_allows_legitimate_append_after_checkpoint(tmp_path):
    ledger = RSILedger(tmp_path / "rsi.db")
    store = RSIMemoryGovernanceLedger(ledger)
    episode, memory, scope = material(ledger)
    candidate = store.nominate(
        episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR,
    )
    old_anchor = store.checkpoint_anchor()
    shadow = store.restore().start_shadow(
        candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR,
    )
    store.append(shadow, memory=memory, expected_record_sha256=candidate.digest())
    store.validate_anchor(old_anchor)
    assert store.checkpoint_anchor()["position"] == old_anchor["position"] + 1
