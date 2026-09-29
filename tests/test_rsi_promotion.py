"""Local end-to-end trusted RSI promotion checks.

These tests use the native fixture evaluator and retained transfer panels only.  They never
contact a remote model or evaluator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.rsi_controller import PracticeEpisodeRunner
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_governance_store import RSIMemoryGovernanceLedger
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
)
from lunar_evolution.rsi_memory_governance import MemoryScope
from lunar_evolution.rsi_native import (
    NativeEvaluationProfile,
    NativeIndependentVerifier,
    NativePopulationGateway,
    native_dependency_fingerprint,
    native_environment_fingerprint,
)
from lunar_evolution.rsi_promotion import NativePromotionEvidence
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer import FrozenMemoryTransferBenchmark, NativeTransferTask

ACTOR = "b" * 64


def _profile(root: Path) -> NativeEvaluationProfile:
    context = build_context(root / "fixture")
    pipeline = context.bundle_pipeline
    pipeline.environment_sha256 = native_environment_fingerprint(pipeline)
    pipeline.dependency_sha256 = native_dependency_fingerprint(root / "fixture", ())
    return NativeEvaluationProfile(context.contract, pipeline, root / "fixture")


def _source(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.db")
    profile = _profile(tmp_path)
    workspace = tmp_path / "source-native"
    gateway = NativePopulationGateway(profile, lambda _request: draft_for_score(7), workspace, actor_fingerprint=ACTOR)
    verifier = NativeIndependentVerifier(profile, workspace)
    request = SolverRequest.build(
        episode_id="practice-source", contract_sha256=profile.contract.digest(),
        evaluator_sha256=profile.pipeline.evaluator.digest(), environment_sha256=profile.pipeline.environment_sha256,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(), solver_id="native_population",
        budget={"candidate_attempts": 1}, practice_charter={"curriculum_enabled": False, "memory_write_enabled": False},
    )
    episode = PracticeEpisode(
        "practice-source", "source-run", request.contract_sha256, request.evaluator_sha256,
        request.environment_sha256, EMPTY_MEMORY_SNAPSHOT.digest(), "native_population", "planned", episode_kind="practice",
    )
    execution = PracticeEpisodeRunner(gateway, verifier, ledger=ledger).run(episode, request)
    assert execution.passed
    memory = MemoryItem(
        "memory-source", "fixture", "fixture gap", "use retained strategy", "score improves",
        "pinned fixture", (profile.contract.digest(),), ("native_population",), "pass",
        execution.verifier.receipt_sha256, execution.episode.episode_id,
    )
    scope = MemoryScope("fixture-scope", "fixture", "fixture-conflict")
    return ledger, profile, execution.episode, memory, scope


def _panels(tmp_path: Path, snapshot: MemorySnapshot, profile: NativeEvaluationProfile):
    def generate(_request, readonly):
        return draft_for_score(7 if readonly.items else 5)

    benchmark = FrozenMemoryTransferBenchmark(generate, tmp_path / "panels", actor_fingerprint=ACTOR)
    practice = benchmark.compare(
        comparison_id="practice-panel", tasks=(NativeTransferTask("practice", profile),), snapshot=snapshot,
    )
    holdout = benchmark.compare(
        comparison_id="holdout-panel", tasks=(NativeTransferTask("holdout", profile),), snapshot=snapshot,
    )
    assert practice.effect == holdout.effect == "improved"
    return benchmark, practice, holdout


def _prepared(tmp_path: Path):
    ledger, profile, episode, memory, scope = _source(tmp_path)
    candidate_store = RSIMemoryGovernanceLedger(ledger)
    candidate = candidate_store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)
    shadow = candidate_store.restore().start_shadow(candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR)
    candidate_store.append(shadow, memory=memory, expected_record_sha256=candidate.digest())
    snapshot = MemorySnapshot("promotion-snapshot", EMPTY_MEMORY_SNAPSHOT.digest(), (memory,))
    benchmark, practice, holdout = _panels(tmp_path, snapshot, profile)
    service = NativePromotionEvidence(
        benchmark, (NativeTransferTask("practice", profile),), (NativeTransferTask("holdout", profile),),
        snapshot, "practice-panel", "holdout-panel",
    )
    store = RSIMemoryGovernanceLedger(ledger, promotion_evidence=service)
    return store, memory, scope, shadow, snapshot, service, practice, holdout


def test_native_promotion_approves_and_activates_from_retained_panels(tmp_path):
    store, memory, scope, shadow, _snapshot, _service, practice, holdout = _prepared(tmp_path)
    approved = store.promote_from_comparisons(
        memory_id=memory.memory_id, memory=memory,
        practice_comparison=json.loads(practice.receipt_path.read_text()),
        holdout_comparison=json.loads(holdout.receipt_path.read_text()),
        transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR,
        expected_record_sha256=shadow.digest(),
    )
    assert approved.state == "approved"
    active = store.activate(
        memory_id=memory.memory_id, memory=memory,
        transition_receipt_sha256="e" * 64, actor_fingerprint=ACTOR,
        expected_record_sha256=approved.digest(),
    )
    assert active.state == "active"
    assert store.active_memories(scope=scope, compatibility=active.authority.compatibility) == (memory,)


def test_forged_panel_and_snapshot_drift_are_rejected(tmp_path):
    store, memory, _scope, shadow, _snapshot, service, practice, holdout = _prepared(tmp_path)
    forged = json.loads(practice.receipt_path.read_text())
    forged["rows"][0]["outcome"]["effect"] = "improved"
    forged["rows"][0]["outcome"]["oriented_score_delta"] = 999.0
    forged_body = {key: value for key, value in forged.items() if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(json.dumps(forged_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(RSILearningError):
        store.promote_from_comparisons(
            memory_id=memory.memory_id, memory=memory, practice_comparison=forged,
            holdout_comparison=json.loads(holdout.receipt_path.read_text()),
            transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR,
            expected_record_sha256=shadow.digest(),
        )
    changed_memory = MemoryItem(
        "memory-source", "fixture", "fixture gap", "different strategy", "score improves",
        "pinned fixture", (memory.compatible_contracts[0],),
        ("native_population",), "pass", memory.receipt_sha256, memory.episode_id,
    )
    drifted = NativePromotionEvidence(
        service.benchmark, service.practice_tasks, service.holdout_tasks,
        MemorySnapshot("changed", None, (changed_memory,)), "practice-panel", "holdout-panel",
    )
    with pytest.raises(RSILearningError):
        drifted.validate_retained()


def test_missing_panel_never_launches_a_new_native_process(tmp_path, monkeypatch):
    _store, _memory, _scope, _shadow, _snapshot, service, _practice, _holdout = _prepared(tmp_path)
    (service.benchmark.workspace_root / "comparisons" / "holdout-panel" / "comparison.json").unlink()
    monkeypatch.setattr(NativePopulationGateway, "run", lambda *_: pytest.fail("promotion launched native process"))
    with pytest.raises(RSILearningError, match="rsi_promotion_receipt_missing"):
        service.validate_retained()


def test_receipt_tamper_is_rejected_and_revoke_hides_active_memory(tmp_path):
    store, memory, scope, shadow, _snapshot, _service, practice, holdout = _prepared(tmp_path)
    approved = store.promote_from_comparisons(
        memory_id=memory.memory_id, memory=memory,
        practice_comparison=json.loads(practice.receipt_path.read_text()),
        holdout_comparison=json.loads(holdout.receipt_path.read_text()),
        transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR,
        expected_record_sha256=shadow.digest(),
    )
    active = store.activate(
        memory_id=memory.memory_id, memory=memory,
        transition_receipt_sha256="e" * 64, actor_fingerprint=ACTOR,
        expected_record_sha256=approved.digest(),
    )
    retained_bytes = practice.receipt_path.read_bytes()
    payload = json.loads(retained_bytes)
    payload["rows"][0]["baseline"]["result"]["solver_score"] = 999
    practice.receipt_path.write_text(json.dumps(payload))
    with pytest.raises(RSILearningError):
        store.active_memories(scope=scope, compatibility=active.authority.compatibility)
    # Restore the retained panel before testing terminal revocation semantics.
    practice.receipt_path.write_bytes(retained_bytes)
    revoked = store.terminalize(
        memory_id=memory.memory_id, state="revoked", memory=memory,
        transition_receipt_sha256="f" * 64, actor_fingerprint=ACTOR,
        expected_record_sha256=active.digest(),
    )
    assert revoked.state == "revoked"
    assert store.active_memories(scope=scope, compatibility=active.authority.compatibility) == ()


def test_raw_fake_promotion_service_has_no_authority(tmp_path):
    store, memory, _scope, shadow, _snapshot, _service, practice, holdout = _prepared(tmp_path)

    class Fake:
        def fingerprint(self):
            return "f" * 64

        def validate_retained(self, *_):
            return {"service_fingerprint": "f" * 64}

    raw = RSIMemoryGovernanceLedger(store.ledger, promotion_evidence=Fake())
    with pytest.raises(RSILearningError, match="rsi_memory_trusted_promotion_unavailable"):
        raw.promote_from_comparisons(
            memory_id=memory.memory_id, memory=memory,
            practice_comparison=json.loads(practice.receipt_path.read_text()),
            holdout_comparison=json.loads(holdout.receipt_path.read_text()),
            transition_receipt_sha256="d" * 64, actor_fingerprint=ACTOR,
            expected_record_sha256=shadow.digest(),
        )


def test_second_panel_task_and_budget_identity_are_pinned(tmp_path):
    ledger, profile, episode, memory, scope = _source(tmp_path)
    store = RSIMemoryGovernanceLedger(ledger)
    candidate = store.nominate(episode=episode, memory=memory, scope=scope, actor_fingerprint=ACTOR)
    shadow = store.restore().start_shadow(candidate, transition_receipt_sha256="c" * 64, actor_fingerprint=ACTOR)
    store.append(shadow, memory=memory, expected_record_sha256=candidate.digest())
    snapshot = MemorySnapshot("promotion-snapshot", EMPTY_MEMORY_SNAPSHOT.digest(), (memory,))
    def generate(_request, readonly):
        return draft_for_score(7 if readonly.items else 5)
    benchmark = FrozenMemoryTransferBenchmark(generate, tmp_path / "budget-panels", actor_fingerprint=ACTOR)
    practice_task = NativeTransferTask("practice", profile, budget=(("candidate_attempts", 1),))
    holdout_task = NativeTransferTask("holdout", profile, budget=(("candidate_attempts", 1),))
    practice = benchmark.compare(comparison_id="practice-budget", tasks=(practice_task,), snapshot=snapshot,
                                 budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 4})
    holdout = benchmark.compare(comparison_id="holdout-budget", tasks=(holdout_task,), snapshot=snapshot,
                                budget={"max_transfer_invocations": 1, "max_evaluator_invocations": 4})
    service = NativePromotionEvidence(benchmark, (practice_task,), (holdout_task,), snapshot,
                                      "practice-budget", "holdout-budget",
                                      practice_budget=(("max_transfer_invocations", 1), ("max_evaluator_invocations", 4)),
                                      holdout_budget=(("max_transfer_invocations", 1), ("max_evaluator_invocations", 4)))
    retained = service.validate_retained(shadow)
    assert retained["practice"]["receipt_sha256"] == practice.receipt_sha256
    assert retained["holdout"]["receipt_sha256"] == holdout.receipt_sha256


def test_missing_receipt_race_is_read_only_and_does_not_launch(tmp_path, monkeypatch):
    _store, _memory, _scope, _shadow, _snapshot, service, _practice, _holdout = _prepared(tmp_path)
    monkeypatch.setattr(NativePromotionEvidence, "_panel", lambda *_args, **_kwargs: (_ for _ in ()).throw(RSILearningError("rsi_promotion_receipt_missing")))
    monkeypatch.setattr(NativePopulationGateway, "run", lambda *_: pytest.fail("promotion launched native process"))
    (service.benchmark.workspace_root / "comparisons" / "holdout-panel" / "comparison.json").unlink()
    with pytest.raises(RSILearningError, match="rsi_promotion_receipt_missing"):
        service.validate_retained()
