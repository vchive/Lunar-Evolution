"""Read real local native publication evidence without assigning a new RSI identity."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
import test_native_trusted_scheduler_e2e as native_fixture
from test_http_transport_deadline import clear_proxy_environment, local_http
from test_native_trusted_scheduler_e2e import fixture

import lunar_evolution.native_trusted_scheduler as scheduler
import lunar_evolution.producer_bundle_transaction as transaction
import lunar_evolution.rsi_native_retained as retained_reader
from lunar_evolution import bundle_evolution
from lunar_evolution.evolution import CandidateArchive
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_native_retained import (
    NativeRetainedCandidateEvidence,
    NativeRetainedEvidenceError,
    read_native_retained_candidate,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")


def inventory(root):
    result = {}
    for path in root.rglob("*"):
        info = path.lstat()
        content = (path.read_bytes() if stat.S_ISREG(info.st_mode) else
                   os.readlink(path) if stat.S_ISLNK(info.st_mode) else None)
        result[path.relative_to(root).as_posix()] = (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, content,
        )
    return result


@pytest.fixture
def published(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        result = scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    assert result.status == "published" and len(requests) == 1
    journal = result.publication.published_journal
    candidate_id = result.publication.admitted_candidate_ids[0]
    archive = CandidateArchive(prepared.context.workspace, requested_strategy="population", read_only=True)
    candidate = next(item for item in archive.records() if item.candidate_id == candidate_id)
    slot = next(item for item in journal.candidates if item.candidate_id == candidate_id)
    arguments = prepared.recovery | {
        "candidate_id": candidate_id,
        "expected_journal_sha256": journal.digest(),
        "expected_producer_execution_receipt_sha256": result.receipt.receipt_sha256,
    }
    return SimpleNamespace(prepared=prepared, result=result, archive=archive,
                           candidate=candidate, slot=slot, arguments=arguments)


def read(published, **changes):
    return read_native_retained_candidate(published.prepared.context.workspace,
                                          **(published.arguments | changes))


def test_retained_native_publication_preserves_separate_evidence_authorities(published):
    retained = read(published)
    prepared, candidate, slot = published.prepared, published.candidate, published.slot
    assert isinstance(retained, NativeRetainedCandidateEvidence)
    assert not isinstance(retained, SolverResult)
    assert retained.workspace == prepared.context.workspace
    for name in ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id"):
        assert getattr(retained, name) == getattr(prepared.intent, name)
    assert retained.candidate_id == candidate.candidate_id
    assert retained.bundle_id == slot.bundle_id
    assert retained.source_entrypoint == "solve/main.py"
    assert retained.contract_sha256 == prepared.context.contract.digest()
    assert retained.evaluator_kind == prepared.recovery["evaluator_kind"]
    assert retained.evaluator_fingerprint == prepared.recovery["evaluator_fingerprint"]
    assert retained.runner_fingerprint == prepared.recovery["runner_fingerprint"]
    assert retained.native_dependency_sha256 == prepared.recovery["dependency_sha256"]
    assert retained.environment_sha256 == prepared.recovery["environment_sha256"]
    assert retained.publication_journal_sha256 == published.result.publication.published_journal.digest()
    assert retained.producer_execution_receipt_sha256 == published.result.receipt.receipt_sha256
    assert retained.candidate_publication_receipt_sha256 == slot.publication_receipt_sha256 == candidate.receipt_sha256
    assert retained.candidate_execution_receipt_sha256 == slot.execution_receipt_sha256
    assert retained.candidate_evaluation_receipt_sha256 == slot.evaluation_receipt_sha256
    assert retained.candidate_completion_sha256 == candidate.bundle_evidence["completion_sha256"]
    assert retained.candidate_evaluation_sha256 == candidate.bundle_evidence["evaluation_sha256"]
    assert retained.source_bundle_sha256 == candidate.bundle_evidence["bundle_sha256"]
    assert retained.entrypoint_source_sha256 == candidate.source_sha256
    assert retained.process_terminal_sha256 == published.result.output.process_terminal_sha256
    assert retained.output_capture_sha256 == published.result.output.output_capture_sha256
    assert retained.envelope_bytes_sha256 == published.result.output.envelope_bytes_sha256

    materials = dict(retained.portable_materials)
    assert materials["source/solve/helper.py"] == b"def choose(limit):\n    return 9\n"
    assert hashlib.sha256(materials["source/solve/main.py"]).hexdigest() == retained.entrypoint_source_sha256
    assert materials["inputs/value"] == b"10"
    assert json.loads(materials["output/result.json"]) == {"value": 9, "claimed_score": 999999}
    report = json.loads(retained.evaluation_report_json)
    assert report["validity"] == 1 and report["combined_score"] == 9
    assert json.loads(materials["evaluation/report.json"])["combined_score"] == 9
    assert json.loads(retained.provenance_json)
    metadata = json.dumps(retained.to_dict(), sort_keys=True)
    assert "def choose" not in metadata and "from helper import choose" not in metadata
    assert not hasattr(retained, "request_sha256")
    assert not hasattr(retained, "memory_snapshot_sha256")
    assert not hasattr(retained, "run") and not hasattr(retained, "to_solver_result")
    assert len(retained.digest()) == 64
    with pytest.raises(FrozenInstanceError):
        retained.candidate_id = "different"


def test_repeated_retained_reads_never_launch_evaluate_stage_or_write(published, monkeypatch):
    prepared = published.prepared
    before = inventory(prepared.context.workspace)

    def forbidden(*_args, **_kwargs):
        pytest.fail("retained evidence reader must not launch, evaluate, stage, or commit")

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", forbidden)
    monkeypatch.setattr(bundle_evolution, "run_candidate_execution_recorded", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(prepared.context.bundle_pipeline, "evaluate_draft_non_publishing", forbidden)
    monkeypatch.setattr(transaction, "stage_producer_bundle_publication", forbidden)
    monkeypatch.setattr(transaction, "commit_producer_bundle_publication", forbidden)
    first = read(published)
    second = read(published)
    assert second == first and second.digest() == first.digest()
    assert inventory(prepared.context.workspace) == before
    assert not (prepared.context.workspace / "rsi.sqlite3").exists()


@pytest.mark.parametrize("field,value", [
    ("expected_journal_sha256", "0" * 64),
    ("expected_producer_execution_receipt_sha256", "0" * 64),
    ("evaluator_kind", "different"),
    ("evaluator_fingerprint", "0" * 64),
    ("runner_fingerprint", "0" * 64),
    ("dependency_sha256", "0" * 64),
    ("environment_sha256", "0" * 64),
])
def test_expected_authority_drift_rejects_without_repair(published, field, value):
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError) as caught:
        read(published, **{field: value})
    assert caught.value.code.startswith("rsi_native_retained_")
    assert inventory(published.prepared.context.workspace) == before


def test_archive_candidate_outside_exact_publication_is_not_admitted(published):
    unrelated = next(item.candidate_id for item in published.archive.records()
                     if item.candidate_id != published.candidate.candidate_id)
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read(published, candidate_id=unrelated)
    assert inventory(published.prepared.context.workspace) == before


def material_path(published, material):
    workspace, candidate = published.prepared.context.workspace, published.candidate
    evidence = candidate.bundle_evidence
    if material == "source":
        return workspace / evidence["source_root"] / "solve/helper.py"
    if material == "source_manifest":
        return workspace / evidence["bundle_path"]
    if material == "candidate_receipt":
        return published.archive.candidate_receipt_path(candidate.candidate_id,
                                                        source_path=workspace / candidate.code_path)
    if material in {"plan", "admission", "completion"}:
        relative = {"plan": "plan.json", "admission": "admission.json", "completion": "attempt/completed.json"}[material]
        return workspace / evidence["run_root"] / relative
    if material in {"evaluator", "input", "output", "evaluation"}:
        relative = {"evaluator": "evaluator.py", "input": "inputs/value",
                    "output": "output/result.json", "evaluation": "evaluation.json"}[material]
        return workspace / evidence["evaluation_path"] / relative
    if material in {"execution_receipt", "published_journal", "terminal"}:
        relative = {"execution_receipt": "execution-receipt.json",
                    "published_journal": "journal.published.json", "terminal": "native-trusted-process-terminal.json"}[material]
        return published.prepared.batch / relative
    raise AssertionError("unknown fixture material")


@pytest.mark.parametrize("material", [
    "source", "source_manifest", "candidate_receipt", "admission", "completion",
    "evaluator", "input", "output", "evaluation", "execution_receipt", "published_journal", "terminal",
])
def test_retained_material_byte_drift_rejects_without_repair(published, material):
    path = material_path(published, material)
    path.write_bytes(path.read_bytes() + b"\nchanged fixture bytes")
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError) as caught:
        read(published)
    assert caught.value.code.startswith("rsi_native_retained_")
    assert inventory(published.prepared.context.workspace) == before


@pytest.mark.parametrize("material", ["completion", "evaluator", "input", "execution_receipt", "published_journal"])
def test_missing_retained_material_rejects_without_recreating_it(published, material):
    path = material_path(published, material)
    path.unlink()
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read(published)
    assert not path.exists()
    assert inventory(published.prepared.context.workspace) == before


@pytest.mark.parametrize("material", ["source", "evaluator"])
def test_same_bytes_symlink_cannot_replace_verified_retained_artifact(published, tmp_path, material):
    path = material_path(published, material)
    alias = tmp_path / "untrusted-alias"
    alias.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(alias)
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read(published)
    assert inventory(published.prepared.context.workspace) == before


@pytest.mark.parametrize("record", ["archive.jsonl", "state.json"])
def test_final_archive_or_population_state_byte_drift_is_not_accepted(published, record):
    path = published.prepared.context.workspace / "evolution" / record
    path.write_bytes(path.read_bytes() + b"\n")
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read(published)
    assert inventory(published.prepared.context.workspace) == before


def test_hash_valid_unknown_journal_cannot_authorize_retained_publication(published):
    unknown = replace(published.result.publication.published_journal,
                      state="unknown", publication_phase="recovery_required", journal_sha256=None)
    path = published.prepared.batch / "journal.published.json"
    path.write_text(json.dumps(unknown.to_dict()))
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError, match="rsi_native_retained_publication_mismatch"):
        read(published, expected_journal_sha256=unknown.digest())
    assert inventory(published.prepared.context.workspace) == before


def test_real_preparation_without_publication_cannot_export_candidate_evidence(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        result = scheduler.run_native_trusted_producer(prepared.context.workspace,
                                                     **(prepared.arguments | {"strategy": None}))
    assert result.status == "prepared" and result.publication is None and len(requests) == 1
    before = inventory(prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read_native_retained_candidate(
            prepared.context.workspace, **prepared.recovery,
            candidate_id="unpublished-candidate", expected_journal_sha256="0" * 64,
            expected_producer_execution_receipt_sha256=result.receipt.receipt_sha256,
        )
    assert inventory(prepared.context.workspace) == before


def test_real_all_rejected_native_batch_cannot_export_candidate_evidence(tmp_path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    invalid_source = native_fixture.MAIN_SOURCE.replace('"value": choose(limit)', '"value": 999')
    assert invalid_source != native_fixture.MAIN_SOURCE
    monkeypatch.setattr(native_fixture, "MAIN_SOURCE", invalid_source)
    with local_http() as (endpoint, requests):
        prepared = fixture(tmp_path, endpoint)
        result = scheduler.run_native_trusted_producer(prepared.context.workspace, **prepared.arguments)
    assert result.status == "all_rejected" and len(requests) == 1
    assert not result.publication.admitted_candidate_ids
    rejected = result.publication.rejected_candidate_ids[0]
    terminal = result.publication.terminal_journal
    assert terminal.state == "all_rejected"
    before = inventory(prepared.context.workspace)
    with pytest.raises(NativeRetainedEvidenceError):
        read_native_retained_candidate(
            prepared.context.workspace, **prepared.recovery,
            candidate_id=rejected, expected_journal_sha256=terminal.digest(),
            expected_producer_execution_receipt_sha256=result.receipt.receipt_sha256,
        )
    assert inventory(prepared.context.workspace) == before


def test_detached_evidence_does_not_accept_new_request_or_memory_attribution(published):
    before = inventory(published.prepared.context.workspace)
    with pytest.raises(TypeError, match="unexpected keyword"):
        read(published, request_sha256="0" * 64)
    with pytest.raises(TypeError, match="unexpected keyword"):
        read(published, memory_snapshot_sha256="0" * 64)
    retained = read(published)
    metadata = retained.to_dict()
    assert metadata["provenance"]["rsi_request_attribution"] == "not_bound"
    assert metadata["provenance"]["memory_authority"] == "none"
    metadata["provenance"]["memory_authority"] = "caller-forged"
    metadata["evaluation_report"]["combined_score"] = 999999
    assert retained.to_dict()["provenance"]["memory_authority"] == "none"
    assert retained.to_dict()["evaluation_report"]["combined_score"] == 9
    assert inventory(published.prepared.context.workspace) == before


def test_artifact_drift_after_material_copy_rejects_the_detached_result(published, monkeypatch):
    original = retained_reader.read_bundle_delivery_materials
    observed = []

    def copy_then_change(*args, **kwargs):
        materials = original(*args, **kwargs)
        path = material_path(published, "evaluator")
        path.write_bytes(path.read_bytes() + b"\n# local interleaving mutation\n")
        observed.append(inventory(published.prepared.context.workspace))
        return materials

    monkeypatch.setattr(retained_reader, "read_bundle_delivery_materials", copy_then_change)
    with pytest.raises(NativeRetainedEvidenceError):
        read(published)
    assert len(observed) == 1
    assert inventory(published.prepared.context.workspace) == observed[0]


@pytest.mark.parametrize("change", ["modified-source", "extra-source"])
def test_portable_source_map_must_match_the_native_bundle_exactly(published, monkeypatch, change):
    original = retained_reader.read_bundle_delivery_materials

    def changed_projection(*args, **kwargs):
        materials = original(*args, **kwargs)
        if change == "modified-source":
            materials["source/solve/helper.py"] += b"\n# mismatched detached bytes\n"
        else:
            materials["source/unbound.py"] = b"print('unbound source')\n"
        return materials

    before = inventory(published.prepared.context.workspace)
    monkeypatch.setattr(retained_reader, "read_bundle_delivery_materials", changed_projection)
    with pytest.raises(NativeRetainedEvidenceError, match="rsi_native_retained_materials_mismatch"):
        read(published)
    assert inventory(published.prepared.context.workspace) == before
