"""Local DRS retains full independent evidence before callback completion and replay."""

from pathlib import Path

import pytest
from test_rsi_controller_runtime_composition import (
    CONTRACT,
    ENVIRONMENT,
    actor_controller,
    evaluator,
)

from lunar_evolution.rsi_actor_evidence_store import (
    ActorCleanRoomEvidenceStore,
    DurableActorCleanRoomVerifier,
)
from lunar_evolution.rsi_identity import component_fingerprint


def durable_controller(tmp_path: Path):
    controller = actor_controller(tmp_path)
    bridge = controller.verifier
    store = ActorCleanRoomEvidenceStore(tmp_path / "independent-evidence")
    controller.verifier = DurableActorCleanRoomVerifier(bridge, store)
    return controller, bridge, store


def test_controller_drs_full_evidence_persists_and_terminal_resume_never_spawns(tmp_path: Path, monkeypatch):
    controller, bridge, store = durable_controller(tmp_path)
    before = component_fingerprint(controller.verifier)
    result = controller.run_drs(
        run_id="durable-evidence-drs", contract_sha256=CONTRACT,
        evaluator_sha256=component_fingerprint(evaluator), environment_sha256=ENVIRONMENT,
        solver_id="lunar-agent-loop", max_practice_rounds=1, max_target_attempts=2,
    )
    assert result.status == "completed" and len(result.practice_episodes) == 1
    assert len(result.target_attempts) == 2 and len(result.memory_snapshot.items) == 1
    for execution in (*result.target_attempts, *result.practice_episodes):
        retained = store.load(execution.episode, execution.request, execution.result,
                              verifier_config=bridge.rsi_fingerprint_config(),
                              verifier_fingerprint=component_fingerprint(bridge))
        assert retained is not None and retained.decision == execution.verifier
        assert retained.evidence.verdict.outcome == "pass"
        assert retained.evidence.verdict.source_sha256 == retained.evidence.source_sha256
        assert controller.callback_checkpoint(result.run_id, "verifier:" + execution.episode.episode_id)[1]["status"] == "completed"
    assert component_fingerprint(controller.verifier) == before
    before_files = {path.name: path.read_bytes() for path in store.root.iterdir()}

    resumed, resumed_bridge, reopened = durable_controller(tmp_path)
    monkeypatch.setattr(resumed.gateway, "run", lambda *_args: pytest.fail("solver must not replay"))
    monkeypatch.setattr(resumed_bridge, "verify_with_evidence", lambda *_args: pytest.fail("verifier process must not replay"))
    replay = resumed.resume(result.run_id)

    assert replay.status == result.status and replay.memory_snapshot == result.memory_snapshot
    assert {path.name: path.read_bytes() for path in reopened.root.iterdir()} == before_files
    assert len(replay.target_attempts) == 2 and len(replay.practice_episodes) == 1
