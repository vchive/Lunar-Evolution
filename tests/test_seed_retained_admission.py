"""Retained local scores require fresh producer authority and a separate receipt pin."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_seed_handoff import _contract, _manifest, _record, _report

import lunar_evolution.seed_handoff as handoff
from lunar_evolution.evolution import CandidateArchive
from lunar_evolution.seed_handoff import (
    RETAINED_ADMISSION_MISMATCH,
    EvaluatorReceipt,
    SeedAdmissionError,
    SeedManifest,
    admit_seed_manifest,
    recover_retained_seed_admission,
)


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


@pytest.fixture
def published(tmp_path: Path):
    contract = _contract()
    producer = tmp_path / "producer"
    producer.mkdir()
    source = producer / "candidate.py"
    source.write_text("answer = 42\n")
    value = _manifest(contract, [_record(
        source.name, hashlib.sha256(source.read_bytes()).hexdigest(),
        origin_kind="external", producer_run_id="producer-once", lineage=["root"],
        metadata={"adapter": "generic_producer"}, external_evidence={"quality": 999999},
    )])
    manifest = SeedManifest.from_dict(value, source_root=producer)
    calls = []

    def evaluate(path, current_contract):
        calls.append(path)
        assert current_contract == contract and path.read_bytes() == source.read_bytes()
        return _report()

    seed = admit_seed_manifest(
        manifest, contract, evaluate, evaluator_kind=manifest.evaluator.kind,
        evaluator_fingerprint=manifest.evaluator.fingerprint,
        dependency_sha256=manifest.dependency_sha256,
        environment_sha256=manifest.environment_sha256,
    ).admitted[0]
    workspace = tmp_path / "canonical"
    workspace.mkdir()
    archive = CandidateArchive(workspace, requested_strategy="openevolve")
    candidate = archive.commit_initial_seeds(
        (seed,), state={"strategy": "openevolve", "status": "completed", "iteration": 1,
                        "best_candidate_id": seed.candidate_id},
        contract_sha256=contract.digest(), evaluator_fingerprint=manifest.evaluator.fingerprint,
        canonical_strategy="openevolve",
    )[0]
    return SimpleNamespace(
        manifest=manifest, seed=seed, candidate=candidate, archive=archive,
        root=workspace / "evolution/candidates" / seed.candidate_id, calls=calls,
    )


def recover(published, *, manifest=None, candidate=None, root=None, pin=None):
    return recover_retained_seed_admission(
        manifest if manifest is not None else published.manifest,
        candidate if candidate is not None else published.candidate,
        candidate_root=root if root is not None else published.root,
        expected_receipt_sha256=pin if pin is not None else published.seed.receipt.receipt_sha256,
    )


def expect_mismatch(published, **changes):
    with pytest.raises(SeedAdmissionError, match=f"^{RETAINED_ADMISSION_MISMATCH}$"):
        recover(published, **changes)


def retained_bytes(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_ino)
            for path in root.rglob("*") if path.is_file()}


def test_repeated_recovery_reuses_original_score_without_evaluation_or_writes(
    published, monkeypatch,
):
    before = retained_bytes(published.archive.workspace)

    def forbidden(*_args, **_kwargs):
        pytest.fail("retained recovery must not evaluate, stage, or publish")

    monkeypatch.setattr(handoff, "_adjudicate_seed", forbidden)
    monkeypatch.setattr(handoff, "_stage_source", forbidden)
    monkeypatch.setattr(CandidateArchive, "commit_initial_seeds", forbidden)
    for _ in range(2):
        restored = recover(published)
        assert restored == published.seed
        assert restored.evaluation.combined_score == 1.25
        published.archive.validate_initial_seeds(
            (restored,), state=published.archive.read_state(),
            contract_sha256=published.manifest.contract_sha256,
            evaluator_fingerprint=published.manifest.evaluator.fingerprint,
            canonical_strategy="openevolve",
        )
    assert len(published.calls) == 1
    assert retained_bytes(published.archive.workspace) == before


@pytest.mark.parametrize("field", [
    "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "dependency_sha256",
    "environment_sha256", "source_sha256", "lineage", "producer_id", "producer_fingerprint",
    "producer_run_id", "material_refs", "external_evidence", "metadata",
])
def test_fresh_manifest_authority_drift_rejects_self_consistent_retained_files(published, field):
    value = published.manifest.to_dict()
    if field == "evaluator_kind":
        value["evaluator"]["kind"] = "another_harness"
    elif field == "evaluator_fingerprint":
        value["evaluator"]["fingerprint"] = "e" * 64
    elif field in {"contract_sha256", "dependency_sha256", "environment_sha256"}:
        value[field] = "e" * 64
    elif field == "source_sha256":
        value["seeds"][0][field] = "e" * 64
    elif field == "lineage":
        value["seeds"][0][field] = ["different-root"]
    elif field == "metadata":
        value["seeds"][0][field] = {"adapter": "different"}
    else:
        changed = {
            "producer_id": "different", "producer_fingerprint": "e" * 64,
            "producer_run_id": "different-run", "material_refs": ["other-material"],
            "external_evidence": {"quality": 888888},
        }
        value["seeds"][0]["provenance"][field] = changed[field]
    before = retained_bytes(published.archive.workspace)
    expect_mismatch(published, manifest=SeedManifest.from_dict(value))
    assert retained_bytes(published.archive.workspace) == before


@pytest.mark.parametrize("field", [
    "candidate_id", "source_sha256", "contract_sha256", "evaluator_kind",
    "evaluator_fingerprint", "dependency_sha256", "environment_sha256", "evaluator_id",
    "quality", "combined_score", "detailed_scores",
])
def test_rehashed_receipt_drift_cannot_replace_pinned_local_result(published, field):
    path = published.root / "receipt.json"
    payload = json.loads(path.read_text())
    if field in {"quality", "combined_score"}:
        payload[field] = 999999
    elif field == "detailed_scores":
        payload[field] = {"route quality": {"value": 999999, "direction": "maximize"}}
    elif field == "evaluator_kind":
        payload[field] = "different_harness"
    elif field in {"candidate_id", "evaluator_id"}:
        payload[field] = "different"
    else:
        payload[field] = "e" * 64
    payload["receipt_sha256"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    )
    path.write_text(json.dumps(payload))
    # Even repinning to the new digest cannot override the expected manifest/report authority.
    expect_mismatch(published, pin=payload["receipt_sha256"])


def test_consistent_local_score_rewrite_still_requires_independent_original_receipt_pin(published):
    forged_report = handoff.EvaluationReport.from_dict(_report(999999))
    forged_receipt = EvaluatorReceipt.from_report(
        forged_report, candidate_id=published.seed.candidate_id,
        source_sha256=published.seed.receipt.source_sha256,
        contract_sha256=published.manifest.contract_sha256,
        evaluator_kind=published.manifest.evaluator.kind,
        evaluator_fingerprint=published.manifest.evaluator.fingerprint,
        dependency_sha256=published.manifest.dependency_sha256,
        environment_sha256=published.manifest.environment_sha256,
    )
    metadata = deepcopy(published.candidate.metadata)
    metadata["seed_handoff"]["receipt_sha256"] = forged_receipt.receipt_sha256
    forged_candidate = replace(published.candidate, evaluation=forged_report, metadata=metadata)
    record = json.loads((published.root / "record.json").read_text())
    record.update(forged_candidate.to_dict())
    record["seed_handoff_evidence"]["receipt_sha256"] = forged_receipt.receipt_sha256
    (published.root / "record.json").write_text(json.dumps(record))
    (published.root / "receipt.json").write_text(json.dumps(forged_receipt.to_dict()))
    expect_mismatch(published, candidate=forged_candidate)


@pytest.mark.parametrize("field", [
    "schema_version", "provenance", "external_evidence", "provenance_sha256",
    "handoff_sha256", "receipt_sha256",
])
def test_published_record_evidence_must_match_fresh_producer_provenance(published, field):
    path = published.root / "record.json"
    payload = json.loads(path.read_text())
    value = payload["seed_handoff_evidence"][field]
    payload["seed_handoff_evidence"][field] = {} if isinstance(value, dict) else "changed"
    path.write_text(json.dumps(payload))
    expect_mismatch(published)


def test_recovered_mutable_metadata_does_not_alias_the_expected_inputs(published):
    restored = recover(published)
    restored.draft.metadata["seed_handoff"]["lineage"].append("untrusted-mutation")
    restored.evaluation.detailed_scores["route quality"]["value"] = 999999
    assert published.candidate.metadata["seed_handoff"]["lineage"] == ["root"]
    assert published.candidate.evaluation.detailed_scores["route quality"]["value"] == 1.25
    assert recover(published) == published.seed


@pytest.mark.parametrize("target", ["candidate.py", "receipt.json", "record.json"])
@pytest.mark.parametrize("change", ["missing", "symlink", "changed", "directory"])
def test_missing_unsafe_or_changed_retained_material_never_repairs(published, target, change):
    path = published.root / target
    content = path.read_bytes()
    path.unlink()
    if change == "symlink":
        outside = published.root.parent / f"outside-{target}"
        outside.write_bytes(content)
        path.symlink_to(outside)
    elif change == "changed":
        path.write_bytes(b"changed")
    elif change == "directory":
        path.mkdir()
    expect_mismatch(published)
    if change == "missing":
        assert not path.exists()


@pytest.mark.parametrize("target", ["receipt.json", "record.json"])
@pytest.mark.parametrize("change", ["duplicate_key", "unknown_field", "too_large"])
def test_retained_json_must_be_strict_and_bounded(published, target, change):
    path = published.root / target
    payload = json.loads(path.read_text())
    if change == "duplicate_key":
        path.write_text('{"schema_version":"1",' + json.dumps(payload)[1:])
    elif change == "unknown_field":
        payload["unverified"] = True
        path.write_text(json.dumps(payload))
    else:
        path.write_bytes(b" " * (handoff.MAX_ARCHIVE_LINE_BYTES + 1))
    expect_mismatch(published)


@pytest.mark.parametrize("target", ["candidate.py", "receipt.json", "record.json"])
def test_same_bytes_inode_replacement_during_recovery_rejects(published, target, monkeypatch):
    original = handoff._retained_seed_snapshot
    counts = {}

    def replace_before_final_read(root, name, maximum):
        counts[name] = counts.get(name, 0) + 1
        if name == target and counts[name] == 2:
            replacement = root / "replacement"
            replacement.write_bytes((root / name).read_bytes())
            os.replace(replacement, root / name)
        return original(root, name, maximum)

    monkeypatch.setattr(handoff, "_retained_seed_snapshot", replace_before_final_read)
    expect_mismatch(published)


def test_ancestor_symlink_cannot_alias_retained_candidate(published, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(published.root.parent, target_is_directory=True)
    expect_mismatch(published, root=alias / published.seed.candidate_id)


@pytest.mark.parametrize("pin", ["invalid", "e" * 64])
def test_explicit_receipt_pin_cannot_be_inferred_from_retained_files(published, pin):
    expect_mismatch(published, pin=pin)


def test_multiple_seed_manifest_is_outside_this_single_admission_helper(published):
    value = published.manifest.to_dict()
    another = deepcopy(value["seeds"][0])
    another["source_path"] = "other.py"
    another["lineage"] = ["other-root"]
    value["seeds"].append(another)
    expect_mismatch(published, manifest=SeedManifest.from_dict(value))


def test_population_canonical_seed_is_recovered_with_original_island(published):
    population_candidate = replace(published.candidate, strategy="population", iteration=0,
                                   island_id=3)
    record_path = published.root / "record.json"
    record = json.loads(record_path.read_text())
    record.update(population_candidate.to_dict())
    record_path.write_text(json.dumps(record))
    restored = recover(published, candidate=population_candidate)
    assert restored.island_id == 3 and restored.strategy == "population"
    assert restored.iteration == 0 and restored.evaluation == published.seed.evaluation


@pytest.mark.parametrize("change", [
    {"iteration": 2}, {"generation": 1}, {"parent_id": "parent"},
    {"island_id": 0}, {"code_path": "evolution/candidates/other/candidate.py"},
    {"metadata": {}},
])
def test_candidate_record_cannot_choose_its_own_seed_shape(published, change):
    expect_mismatch(published, candidate=replace(published.candidate, **change))
