from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution import NativeEpisodeClaim, RSILearningError, RSILedger
from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest

HEX = "a" * 64


def make_request(episode_id: str = "native-episode") -> SolverRequest:
    return SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256="b" * 64,
        environment_sha256="c" * 64,
        memory_snapshot_sha256="d" * 64,
        solver_id="fixture",
        solver_settings={"iterations": 1},
        budget={"wall_timeout_seconds": 10},
        practice_charter={"goal": "fixture"},
    )


def test_native_claim_binds_request_and_plan_and_pending_recovery_is_quarantined(tmp_path: Path):
    store = RSILedger(tmp_path / "rsi.sqlite3")
    request = make_request()
    claim = store.claim_native_episode(request, plan_sha256=HEX)
    assert isinstance(claim, NativeEpisodeClaim)
    assert claim.status == "started"
    assert claim.request_sha256 == request.digest()
    assert store.inspect_native_episode_claim(request, plan_sha256=HEX) == claim
    with pytest.raises(RSILearningError, match="rsi_native_episode_recovery_required"):
        store.claim_native_episode(request, plan_sha256=HEX)
    with pytest.raises(RSILearningError, match="rsi_native_episode_recovery_required"):
        store.recover_native_episode_claim(request, plan_sha256=HEX)


@pytest.mark.parametrize("field", ["contract_sha256", "solver_id"])
def test_native_claim_rejects_request_drift_before_second_claim(tmp_path: Path, field: str):
    store = RSILedger(tmp_path / "rsi.sqlite3")
    request = make_request()
    store.claim_native_episode(request, plan_sha256=HEX)
    changed = replace(request, **{field: "e" * 64 if field.endswith("sha256") else "other"})
    with pytest.raises(RSILearningError, match="rsi_native_episode_claim_binding_drift"):
        store.claim_native_episode(changed, plan_sha256=HEX)


def test_native_claim_publishes_and_replays_exact_terminal_result(tmp_path: Path):
    store = RSILedger(tmp_path / "rsi.sqlite3")
    request = make_request()
    store.claim_native_episode(request, plan_sha256=HEX)
    result = DeterministicMockSolver().run(request)
    claim = store.publish_native_episode_result(request, plan_sha256=HEX, result=result)
    assert claim.status == "completed"
    assert store.recover_native_episode_claim(request, plan_sha256=HEX) == claim
    assert store.publish_native_episode_result(request, plan_sha256=HEX, result=result) == claim
    assert store.episode_result(request.episode_id) == (request, result)


def test_native_claim_unknown_result_remains_recovery_only(tmp_path: Path):
    store = RSILedger(tmp_path / "rsi.sqlite3")
    request = make_request()
    store.claim_native_episode(request, plan_sha256=HEX)
    result = replace(DeterministicMockSolver().run(request), status="unknown", terminal_reason="worker_lost")
    claim = store.publish_native_episode_result(request, plan_sha256=HEX, result=result)
    assert claim.status == "unknown"
    assert store.recover_native_episode_claim(request, plan_sha256=HEX) == claim
    with pytest.raises(RSILearningError, match="rsi_native_episode_claim_binding_drift"):
        store.inspect_native_episode_claim(request, plan_sha256="f" * 64)
