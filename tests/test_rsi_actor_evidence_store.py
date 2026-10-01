"""Full local clean-room evidence survives restart without duplicating evaluation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from test_rsi_actor_verifier import completed, failing_evaluator, trusted_evaluator

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_actor_evidence_store import (
    MAX_ACTOR_EVIDENCE_BYTES,
    ActorCleanRoomEvidenceStore,
    ActorEvidenceStoreError,
    DurableActorCleanRoomVerifier,
)
from lunar_evolution.rsi_cleanroom_admission import (
    CleanRoomAdmissionGate,
    CleanRoomAdmissionRequest,
)
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_memory_governance import MemoryGovernanceStore


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pins(bridge):
    return {"verifier_config": bridge.rsi_fingerprint_config(), "verifier_fingerprint": component_fingerprint(bridge)}


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    bridge, episode, request, result = completed(tmp_path_factory.mktemp("actor-evidence-fixture"), trusted_evaluator)
    decision, evidence = bridge.verify_with_evidence(episode, request, result)
    assert decision.outcome == "pass"
    return bridge, episode, request, result, decision, evidence


def retained(tmp_path: Path, bundle):
    bridge, episode, request, result, decision, evidence = bundle
    store = ActorCleanRoomEvidenceStore(tmp_path / "evidence")
    record = store.save(episode, request, result, decision, evidence, **pins(bridge))
    return store, record


def record_path(store, episode):
    return store.root / store._name(episode.episode_id)


def test_full_verdict_and_original_pins_survive_reopen_readonly_replay(tmp_path: Path, bundle, monkeypatch):
    bridge, episode, request, result, decision, evidence = bundle
    store, record = retained(tmp_path, bundle)
    reopened = ActorCleanRoomEvidenceStore(store.root)
    monkeypatch.setattr("lunar_evolution.rsi_actor_evidence_store._publish", lambda *_: pytest.fail("replay must not write"))
    replay = reopened.save(episode, request, result, decision, evidence, **pins(bridge))
    assert replay.to_bytes() == record.to_bytes()
    assert replay.evidence == evidence and replay.evidence.verdict == evidence.verdict
    assert replay.to_dict()["binding"]["verifier_config"] == bridge.rsi_fingerprint_config()
    assert replay.to_dict()["binding"]["request"] == request.to_dict()
    assert replay.to_dict()["binding"]["result"] == result.to_dict()
    assert reopened.load(episode.attach_verifier(decision), request, result, **pins(bridge)).decision == decision


def test_wrapper_persists_before_return_and_replays_without_artifacts_or_spawn(tmp_path: Path, monkeypatch):
    bridge, episode, request, result = completed(tmp_path / "actor", trusted_evaluator)
    store = ActorCleanRoomEvidenceStore(tmp_path / "evidence")
    wrapper = DurableActorCleanRoomVerifier(bridge, store)
    before = component_fingerprint(wrapper)
    decision = wrapper.verify(episode, request, result)
    assert store.load(episode, request, result, **pins(bridge)).decision == decision
    (bridge.workspace_root / "episodes" / episode.episode_id / "candidate.py").unlink()
    monkeypatch.setattr(bridge, "verify_with_evidence", lambda *_: pytest.fail("evaluator replay forbidden"))
    replay = DurableActorCleanRoomVerifier(bridge, ActorCleanRoomEvidenceStore(store.root)).verify(episode, request, result)
    assert replay == decision and component_fingerprint(wrapper) == before


def test_attached_episode_verifier_cannot_disagree_with_retained_decision(tmp_path: Path, bundle):
    bridge, episode, request, result, decision, _evidence = bundle
    store, _ = retained(tmp_path, bundle)
    changed = episode.attach_verifier(replace(decision, receipt_sha256=digest("changed receipt")))
    with pytest.raises(ActorEvidenceStoreError, match="decision_drift"):
        store.load(changed, request, result, **pins(bridge))


def test_unknown_claim_does_not_spawn_and_explicit_retained_evidence_can_complete_it(tmp_path: Path, bundle, monkeypatch):
    bridge, episode, request, result, decision, evidence = bundle
    store = ActorCleanRoomEvidenceStore(tmp_path / "evidence")
    store.begin(episode, request, result, **pins(bridge))
    monkeypatch.setattr(bridge, "verify_with_evidence", lambda *_: pytest.fail("unknown cannot retry evaluator"))
    wrapper = DurableActorCleanRoomVerifier(bridge, store)
    with pytest.raises(ActorEvidenceStoreError, match="unknown_reconcile_required"):
        wrapper.verify(episode, request, result)
    store.save(episode, request, result, decision, evidence, **pins(bridge))
    assert wrapper.verify(episode, request, result) == decision


def test_save_failure_retains_unknown_claim_instead_of_retrying_evaluator(tmp_path: Path, bundle, monkeypatch):
    bridge, episode, request, result, decision, evidence = bundle
    store = ActorCleanRoomEvidenceStore(tmp_path / "evidence")
    calls = []

    def observed(*_):
        calls.append("one evaluation")
        return decision, evidence

    monkeypatch.setattr(bridge, "verify_with_evidence", observed)
    monkeypatch.setattr(store, "save", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fixture save failure")))
    wrapper = DurableActorCleanRoomVerifier(bridge, store)
    with pytest.raises(OSError):
        wrapper.verify(episode, request, result)
    restarted = DurableActorCleanRoomVerifier(bridge, ActorCleanRoomEvidenceStore(store.root))
    with pytest.raises(ActorEvidenceStoreError, match="unknown_reconcile_required"):
        restarted.verify(episode, request, result)
    assert calls == ["one evaluation"]


def test_fail_and_unresolved_results_are_retained_but_cannot_be_admitted(tmp_path: Path):
    bridge, episode, request, result = completed(tmp_path / "actor", failing_evaluator)
    store = ActorCleanRoomEvidenceStore(tmp_path / "evidence")
    decision, evidence = DurableActorCleanRoomVerifier(bridge, store).verify_with_evidence(episode, request, result)
    assert decision.outcome == "fail" and evidence.verdict.outcome == "fail"
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    with pytest.raises(ActorEvidenceStoreError, match="admission_not_pass"):
        store.admit(episode, request, result, **pins(bridge), admission=admission_request(request, evidence),
                    gate=CleanRoomAdmissionGate(governance))
    (bridge.workspace_root / "episodes" / episode.episode_id / "candidate.py").unlink()
    other_store = ActorCleanRoomEvidenceStore(tmp_path / "unresolved")
    unresolved, diagnostic = DurableActorCleanRoomVerifier(bridge, other_store).verify_with_evidence(episode, request, result)
    assert unresolved.outcome == "unresolved" and diagnostic.verdict is None
    assert other_store.load(episode, request, result, **pins(bridge)).evidence == diagnostic


@pytest.mark.parametrize("changed", ["request", "result", "contract", "task", "fingerprint", "missing_pin"])
def test_changed_identity_or_original_pins_fail_before_replay(tmp_path: Path, bundle, changed: str):
    bridge, episode, request, result, _decision, _evidence = bundle
    store, _ = retained(tmp_path, bundle)
    config = pins(bridge)
    if changed == "request":
        request = replace(request, budget=(("max_calls", 1),))
    elif changed == "result":
        result = replace(result, solver_score=42.0)
    elif changed == "contract":
        config["verifier_config"]["contract_sha256"] = digest("different contract")
    elif changed == "task":
        config["verifier_config"]["task_input_sha256"] = digest("different task")
    elif changed == "fingerprint":
        config["verifier_fingerprint"] = digest("different verifier")
    else:
        config["verifier_config"].pop("environment_sha256")
    with pytest.raises(ActorEvidenceStoreError):
        store.load(episode, request, result, **config)


def rehash(value):
    payload = {key: item for key, item in value.items() if key != "record_sha256"}
    value["record_sha256"] = hashlib.sha256(canonical_json(payload, maximum=MAX_ACTOR_EVIDENCE_BYTES)).hexdigest()
    return canonical_json(value, maximum=MAX_ACTOR_EVIDENCE_BYTES)


@pytest.mark.parametrize("changed", ["source", "verdict", "decision", "actor_manifest", "unexpected"])
def test_rehashed_record_still_requires_cross_field_evidence_binding(tmp_path: Path, bundle, changed: str):
    bridge, episode, request, result, _decision, _evidence = bundle
    store, record = retained(tmp_path, bundle)
    value = record.to_dict()
    if changed == "source":
        value["evidence"]["source_sha256"] = digest("changed source")
    elif changed == "verdict":
        value["evidence"]["verdict"]["actor_evidence_sha256"] = digest("changed actor evidence")
    elif changed == "decision":
        value["decision"]["receipt_sha256"] = digest("changed decision")
    elif changed == "actor_manifest":
        value["evidence"]["candidate_manifest_sha256"] = value["evidence"]["source_sha256"]
    else:
        value["unexpected"] = True
    record_path(store, episode).write_bytes(rehash(value))
    with pytest.raises(ActorEvidenceStoreError):
        store.load(episode, request, result, **pins(bridge))


@pytest.mark.parametrize("invalid", ["noncanonical", "duplicate", "oversize", "symlink", "hardlink", "fifo"])
def test_unsafe_or_malformed_record_is_fail_closed(tmp_path: Path, bundle, invalid: str):
    bridge, episode, request, result, _decision, _evidence = bundle
    store, record = retained(tmp_path, bundle)
    target = record_path(store, episode)
    if invalid == "noncanonical":
        target.write_text(json.dumps(record.to_dict(), indent=2))
    elif invalid == "duplicate":
        target.write_bytes(record.to_bytes()[:-1] + b',"protocol":"duplicate"}')
    elif invalid == "oversize":
        target.write_bytes(b"x" * (MAX_ACTOR_EVIDENCE_BYTES + 1))
    else:
        displaced = tmp_path / "record.json"
        target.rename(displaced)
        if invalid == "symlink":
            target.symlink_to(displaced)
        elif invalid == "hardlink":
            target.hardlink_to(displaced)
        else:
            os.mkfifo(target)
    with pytest.raises(ActorEvidenceStoreError):
        store.load(episode, request, result, **pins(bridge))


def test_root_replacement_and_symlinked_ancestor_are_rejected(tmp_path: Path, bundle):
    bridge, episode, request, result, _decision, _evidence = bundle
    store, _ = retained(tmp_path, bundle)
    original = tmp_path / "original"
    store.root.rename(original)
    store.root.mkdir()
    with pytest.raises(ActorEvidenceStoreError, match="directory_changed"):
        store.load(episode, request, result, **pins(bridge))
    linked = tmp_path / "linked"
    linked.symlink_to(original, target_is_directory=True)
    with pytest.raises(ActorEvidenceStoreError, match="storage_invalid"):
        ActorCleanRoomEvidenceStore(linked / "child")


@pytest.mark.parametrize("replace_directory", [False, True])
def test_same_bytes_replacement_during_read_is_rejected(tmp_path: Path, bundle, monkeypatch, replace_directory):
    bridge, episode, request, result, _decision, _evidence = bundle
    store, _ = retained(tmp_path, bundle)
    target = record_path(store, episode)
    original_read, replaced = os.read, False

    def racing_read(descriptor, size):
        nonlocal replaced
        data = original_read(descriptor, size)
        if data and not replaced:
            replaced = True
            if replace_directory:
                store.root.rename(tmp_path / "retained-original")
                store.root.mkdir()
            else:
                content = target.read_bytes()
                target.rename(tmp_path / "retained-original.json")
                target.write_bytes(content)
        return data

    monkeypatch.setattr("lunar_evolution.rsi_actor_evidence_store.os.read", racing_read)
    with pytest.raises(ActorEvidenceStoreError, match="storage_changed|directory_changed"):
        store.load(episode, request, result, **pins(bridge))


def admission_request(request, evidence):
    return CleanRoomAdmissionRequest(
        admission_id="independent-admission", memory_snapshot_sha256=digest("frozen memory"),
        memory_item_sha256=digest("memory item"), source_episode_id=request.episode_id,
        parent_snapshot_sha256=request.memory_snapshot_sha256, scope="fixture", compatibility={},
        contract_sha256=request.contract_sha256, expected_source_sha256=evidence.source_sha256,
        expected_dependency_sha256=evidence.dependency_sha256,
        expected_task_input_sha256=evidence.task_input_sha256, expected_evaluator_sha256=request.evaluator_sha256,
    )


def test_complete_original_pins_feed_only_verified_governance_and_replay(tmp_path: Path, bundle):
    bridge, episode, request, result, decision, evidence = bundle
    store, _ = retained(tmp_path, bundle)
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    admission = admission_request(request, evidence)
    gate = CleanRoomAdmissionGate(governance)
    verified = store.admit(episode, request, result, **pins(bridge), admission=admission, gate=gate)
    replay = store.admit(episode, request, result, **pins(bridge), admission=admission, gate=gate)
    assert verified == replay and verified.state == "verified"
    assert verified.verifier_receipt_sha256 == evidence.verdict.receipt_sha256 != decision.receipt_sha256
    assert len(governance.history(verified.admission_id)) == 2


@pytest.mark.parametrize("field", ["contract_sha256", "source_episode_id", "expected_source_sha256",
                                  "expected_dependency_sha256", "expected_task_input_sha256", "expected_evaluator_sha256"])
def test_admission_requires_independent_complete_original_pins(tmp_path: Path, bundle, field: str):
    bridge, episode, request, result, _decision, evidence = bundle
    store, _ = retained(tmp_path, bundle)
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    admission = replace(admission_request(request, evidence), **{field: "different" if field == "source_episode_id" else digest("different pin")})
    with pytest.raises(ActorEvidenceStoreError, match="admission_pin_drift"):
        store.admit(episode, request, result, **pins(bridge), admission=admission, gate=CleanRoomAdmissionGate(governance))
    assert governance.get(admission.admission_id) is None
