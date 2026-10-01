"""Explicit local translation preserves provenance and never grants target approval."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot, RSILearningError
from lunar_evolution.rsi_memory_translation import (
    MemoryTranslationError,
    SolverMemoryMapping,
    TranslatedMemoryCandidate,
    recover_translation,
    translate_memory,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def source_item() -> MemoryItem:
    return MemoryItem(
        memory_id="source-memory", problem_family="local-fixture",
        trigger="source trigger", strategy="source strategy", expected_result="expected pass",
        failure_boundary="bounded source", compatible_contracts=(digest("source-contract"),),
        compatible_solvers=("source-solver",), verifier_outcome="pass",
        receipt_sha256=digest("source-verifier"), episode_id="source-episode",
        condition="input is sorted", action="use the source search primitive",
        observed_result="source episode passed", applicability="monotonic keys only",
    )


def mapping() -> SolverMemoryMapping:
    return SolverMemoryMapping(
        "mapping-v1", "source-solver", "target-solver", digest("source-solver-v1"),
        digest("target-solver-v1"), digest("source-contract"), digest("target-contract"),
        "target input preserves ordering", "use the declared target search primitive",
        "target monotonic key representation only", "explicit local fixture mapping",
    )


def translated(source: MemoryItem | None = None) -> TranslatedMemoryCandidate:
    item = source_item() if source is None else source
    return translate_memory(
        MemorySnapshot("source-snapshot", None, (item,)), item.memory_id, mapping(),
        expected_source_receipt_sha256=item.receipt_sha256, candidate_id="target-candidate",
    )


def test_translation_freezes_causal_provenance_and_target_only_candidate() -> None:
    source = source_item()
    result = translated(source)
    payload = result.to_dict()
    assert payload["source_memory"] == source.to_dict()
    assert payload["source_receipt_sha256"] == source.receipt_sha256
    assert payload["source_causal"] == {
        "condition": source.condition, "action": source.action,
        "observed_result": source.observed_result, "applicability": source.applicability,
    }
    assert payload["candidate"]["observed_result"] == source.observed_result
    assert payload["candidate"]["active_eligible"] is False
    assert payload["candidate"]["required_gates"] == ["verified", "holdout"]
    draft = result.draft_memory_item()
    assert draft.compatible_solvers == ("target-solver",)
    assert draft.compatible_contracts == (digest("target-contract"),)
    assert draft.status == draft.verifier_outcome == "unresolved"
    assert draft.receipt_sha256 == result.receipt_sha256
    with pytest.raises(RSILearningError, match="snapshot_unapproved"):
        MemorySnapshot("cannot-activate", None, (draft,))
    assert source.status == "approved"


def test_translation_recovery_replays_without_mutation_or_callbacks() -> None:
    source = source_item()
    snapshot = MemorySnapshot("source-snapshot", None, (source,))
    result = translated(source)
    before = snapshot.to_bytes()
    assert recover_translation(
        result.to_bytes(), source_snapshot=snapshot, mapping=mapping(),
        expected_source_receipt_sha256=source.receipt_sha256,
        expected_receipt_sha256=result.receipt_sha256,
    ) == result
    assert snapshot.to_bytes() == before
    mutable = result.to_dict()
    mutable["mapping"]["target_solver_id"] = "caller-changed"
    mutable["source_memory"]["compatible_solvers"].append("caller-changed")
    assert result.to_dict()["mapping"]["target_solver_id"] == "target-solver"
    assert result.source_item.compatible_solvers == ("source-solver",)


@pytest.mark.parametrize("changed", ["source_solver_id", "source_contract_sha256"])
def test_translation_rejects_undeclared_source_compatibility(changed: str) -> None:
    value = "unknown-solver" if changed.endswith("id") else digest("unknown-contract")
    with pytest.raises(MemoryTranslationError, match="incompatible"):
        translate_memory(
            MemorySnapshot("source-snapshot", None, (source_item(),)), "source-memory",
            replace(mapping(), **{changed: value}),
            expected_source_receipt_sha256=digest("source-verifier"), candidate_id="candidate",
        )


def test_missing_source_and_changed_receipt_fail_before_translation() -> None:
    snapshot = MemorySnapshot("source-snapshot", None, (source_item(),))
    with pytest.raises(MemoryTranslationError, match="source_missing"):
        translate_memory(snapshot, "missing", mapping(), expected_source_receipt_sha256=digest("source-verifier"), candidate_id="candidate")
    with pytest.raises(MemoryTranslationError, match="source_receipt_drift"):
        translate_memory(snapshot, "source-memory", mapping(), expected_source_receipt_sha256=digest("wrong"), candidate_id="candidate")


@pytest.mark.parametrize("outcome", ["fail", "unresolved"])
def test_unverified_source_cannot_be_projected(outcome: str) -> None:
    source = replace(source_item(), status="unresolved", verifier_outcome=outcome)
    with pytest.raises(MemoryTranslationError, match="source_unverified"):
        TranslatedMemoryCandidate(digest("snapshot"), source, mapping(), "candidate")


def test_same_solver_and_reused_candidate_identity_are_rejected() -> None:
    with pytest.raises(MemoryTranslationError, match="same_solver"):
        replace(mapping(), target_solver_id="source-solver")
    with pytest.raises(MemoryTranslationError, match="candidate_identity_conflict"):
        TranslatedMemoryCandidate(digest("snapshot"), source_item(), mapping(), "source-memory")


@pytest.mark.parametrize("changed", ["source", "snapshot", "mapping"])
def test_recovery_checks_original_source_and_mapping_pins(changed: str) -> None:
    receipt = translated().to_bytes()
    source = source_item()
    snapshot_id = "source-snapshot"
    declared = mapping()
    if changed == "source":
        source = replace(source, observed_result="changed source fact")
    elif changed == "snapshot":
        snapshot_id = "changed-snapshot"
    else:
        declared = replace(declared, target_solver_fingerprint=digest("new-target"))
    with pytest.raises(MemoryTranslationError, match="receipt_drift"):
        recover_translation(
            receipt, source_snapshot=MemorySnapshot(snapshot_id, None, (source,)), mapping=declared,
            expected_source_receipt_sha256=source.receipt_sha256,
            expected_receipt_sha256=translated().receipt_sha256,
        )


@pytest.mark.parametrize("changed", ["active", "compatibility", "extra", "digest", "format", "duplicate"])
def test_tampered_or_noncanonical_translation_receipts_are_rejected(changed: str) -> None:
    result = translated()
    payload = result.to_dict()
    if changed == "active":
        payload["candidate"]["active_eligible"] = True
    elif changed == "compatibility":
        payload["candidate"]["compatible_solvers"].append("undeclared")
    elif changed == "extra":
        payload["unexpected"] = True
    elif changed == "digest":
        payload["receipt_sha256"] = digest("wrong")
    content = canonical_json(payload, maximum=256 * 1024)
    if changed == "format":
        content = json.dumps(payload, indent=2).encode()
    elif changed == "duplicate":
        content = b'{"protocol":"shadow",' + content[1:]
    with pytest.raises(MemoryTranslationError):
        recover_translation(
            content, source_snapshot=MemorySnapshot("source-snapshot", None, (source_item(),)),
            mapping=mapping(), expected_source_receipt_sha256=digest("source-verifier"),
            expected_receipt_sha256=result.receipt_sha256,
        )


def test_legacy_source_projection_preserves_original_wire_and_explicit_causal_fields() -> None:
    legacy_payload = source_item().to_dict()
    for name in ("condition", "action", "observed_result", "applicability"):
        legacy_payload.pop(name)
    legacy = MemoryItem.from_dict(legacy_payload)
    result = translated(legacy)
    assert result.to_dict()["source_memory"] == legacy_payload
    assert result.to_dict()["source_causal"]["condition"] == legacy.trigger
    assert result.to_dict()["candidate"]["observed_result"] == legacy.expected_result


def test_legitimate_new_translation_cannot_replace_pinned_recovery_receipt() -> None:
    original = translated()
    changed = replace(original, candidate_id="another-candidate")
    with pytest.raises(MemoryTranslationError, match="receipt_drift"):
        recover_translation(
            changed.to_bytes(), source_snapshot=MemorySnapshot("source-snapshot", None, (source_item(),)),
            mapping=mapping(), expected_source_receipt_sha256=digest("source-verifier"),
            expected_receipt_sha256=original.receipt_sha256,
        )
