from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_preflight import (
    compute_archive_prefix_digest,
    derive_producer_bundle_candidate_id,
    preflight_producer_bundle_publication,
)
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
)
from lunar_evolution.producer_bundle_recovery import (
    ProducerBundleRecoveryError,
    resume_producer_bundle_publication,
)


def _d(letter: str) -> str:
    return letter * 64


def _plan() -> ProducerBundleAdmissionPlan:
    return ProducerBundleAdmissionPlan(
        contract_sha256=_d("0"), evaluator_kind="callback", evaluator_fingerprint=_d("1"),
        runner_fingerprint=_d("2"), dependency_sha256=_d("3"), environment_sha256=_d("4"),
        bundles=(ProducerBundleAdmissionItem(
            bundle_id="bundle-1", bundle_sha256=_d("a"), draft_bundle_sha256=_d("a"),
            entrypoint="main.py", material_paths=("main.py",), producer_fingerprint=_d("b"),
        ),),
    )


def _journal(plan: ProducerBundleAdmissionPlan, *, state="executing", marker=None):
    empty = hashlib.sha256(b"").hexdigest()
    config = {"strategy": "population", "num_islands": 1}
    active_ids = {"0": []}
    state_payload = {"strategy": "population", "config": config, "active_ids": active_ids}
    state_bytes = json.dumps(state_payload, sort_keys=True).encode()
    state_sha = hashlib.sha256(state_bytes).hexdigest()
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    candidate_id = derive_producer_bundle_candidate_id("journal-1", 0, "bundle-1", _d("a"))
    item = ProducerBundlePublicationCandidate(
        candidate_id=candidate_id, bundle_id="bundle-1", bundle_sha256=_d("a"), parent_id=None,
        generation=0, iteration=0, island_id=0, preparation_receipt_sha256=_d("7"),
        execution_receipt_sha256=None,
        evaluation_receipt_sha256=None,
        publication_receipt_sha256=None,
        status="planned",
    )
    return build_producer_bundle_publication_journal(
        journal_id="journal-1", run_id="run-1", parent_task_id="parent-1", task_id="task-1",
        admission_sha256=plan.digest(), archive_prefix_sha256=compute_archive_prefix_digest(
            empty, state_sha, strategy_config_sha256=config_sha,
            active_ids_sha256=hashlib.sha256(b'{"0":[]}').hexdigest(),
        ), base_archive_sha256=empty, base_state_sha256=state_sha,
        contract_sha256=plan.contract_sha256, evaluator_kind=plan.evaluator_kind,
        evaluator_fingerprint=plan.evaluator_fingerprint, runner_fingerprint=plan.runner_fingerprint,
        dependency_sha256=plan.dependency_sha256, environment_sha256=plan.environment_sha256,
        budget_sha256=_d("5"), strategy="population", population_config_sha256=config_sha,
        num_islands=1, candidates=(item,), state=state,
        publication_phase=("preflight" if state == "prepared" else ("staged" if state in {"executing", "publishing"} else "recovery_required")),
        **({"terminal_marker_sha256": marker} if marker else {}),
    )


def _workspace(tmp_path: Path, plan, journal):
    root = tmp_path / "workspace"
    batch = root / "evolution" / "producer-batches" / journal.journal_id
    (batch / "stage" / "candidates" / journal.candidates[0].candidate_id).mkdir(parents=True)
    state = {"strategy": "population", "config": {"strategy": "population", "num_islands": 1}, "active_ids": {"0": []}}
    state_bytes = json.dumps(state, sort_keys=True).encode()
    (root / "evolution" / "state.json").write_bytes(state_bytes)
    (root / "evolution" / "archive.jsonl").write_text("", encoding="utf-8")
    prepared = _journal(plan, state="prepared")
    if journal.native_execution_receipt_sha256 is not None or journal.python_handoff_sha256 is not None:
        prepared = replace(
            prepared,
            native_execution_receipt_sha256=journal.native_execution_receipt_sha256,
            python_handoff_sha256=journal.python_handoff_sha256,
            journal_sha256=None,
        )
    (batch / "journal.json").write_text(json.dumps(journal.to_dict(), sort_keys=True), encoding="utf-8")
    receipt = preflight_producer_bundle_publication(root, plan, prepared)
    (batch / "preflight.json").write_text(json.dumps(receipt.to_dict(), sort_keys=True), encoding="utf-8")
    cid = journal.candidates[0].candidate_id
    candidate_dir = batch / "stage" / "candidates" / cid
    record = b'{"candidate_id":"' + cid.encode() + b'"}\n'
    receipt_bytes = b'{"publication_receipt_sha256":"' + _d("c").encode() + b'"}\n'
    (candidate_dir / "record.json").write_bytes(record)
    (candidate_dir / "receipt.json").write_bytes(receipt_bytes)
    (batch / "stage" / "archive.jsonl").write_bytes(b"")
    (batch / "stage" / "state.json").write_bytes(state_bytes)
    manifest_body = {
        "schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": journal.journal_id, "journal_sha256": journal.journal_sha256,
        "preflight_sha256": receipt.digest(), "base_archive_sha256": journal.base_archive_sha256,
        "base_state_sha256": journal.base_state_sha256, "archive_after_sha256": hashlib.sha256(b"").hexdigest(),
        "state_after_sha256": hashlib.sha256(state_bytes).hexdigest(), "candidate_ids": [cid], "status": "staged",
        "files": [{"candidate_id": cid, "paths": [
            {"path": "record.json", "size": len(record), "sha256": hashlib.sha256(record).hexdigest()},
            {"path": "receipt.json", "size": len(receipt_bytes), "sha256": hashlib.sha256(receipt_bytes).hexdigest()},
        ], "record_sha256": hashlib.sha256(record).hexdigest(), "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest()}],
    }
    manifest_body["manifest_sha256"] = hashlib.sha256(json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (batch / "manifest.json").write_text(json.dumps({**manifest_body}, sort_keys=True), encoding="utf-8")
    return root


def test_exact_staged_resume_reuses_evidence(tmp_path: Path):
    plan = _plan()
    journal = _journal(plan)
    root = _workspace(tmp_path, plan, journal)
    result = resume_producer_bundle_publication(root, plan, journal)
    assert result.status == "resume"
    assert result.candidate_ids == (journal.candidates[0].candidate_id,)


def test_changed_receipt_fails_closed(tmp_path: Path):
    plan = _plan()
    journal = _journal(plan)
    root = _workspace(tmp_path, plan, journal)
    path = root / "evolution" / "producer-batches" / journal.journal_id / "stage" / "candidates" / journal.candidates[0].candidate_id / "record.json"
    path.write_text('{"changed":true}\n', encoding="utf-8")
    with pytest.raises(ProducerBundleRecoveryError) as caught:
        resume_producer_bundle_publication(root, plan, journal)
    assert caught.value.code == "producer_bundle_recovery_evidence_mismatch"


def test_python_handoff_drift_fails_closed_on_resume(tmp_path: Path):
    plan = _plan()
    journal = replace(
        _journal(plan), native_execution_receipt_sha256=_d("8"),
        python_handoff_sha256=_d("9"), journal_sha256=None,
    )
    # Recompute the immutable durable journal with a different handoff identity while keeping
    # the caller's original journal.  Recovery must reject the drift before reading evidence.
    root = _workspace(tmp_path, plan, journal)
    batch_journal = root / "evolution" / "producer-batches" / journal.journal_id / "journal.json"
    durable = replace(journal, python_handoff_sha256=_d("0"), journal_sha256=None)
    batch_journal.write_text(json.dumps(durable.to_dict(), sort_keys=True), encoding="utf-8")
    with pytest.raises(ProducerBundleRecoveryError) as caught:
        resume_producer_bundle_publication(root, plan, journal)
    assert caught.value.code == "producer_bundle_recovery_journal_mismatch"


@pytest.mark.parametrize("mutation", ["caller_omits", "caller_swaps", "durable_drifts"])
def test_native_receipt_link_is_immutable_on_resume(tmp_path: Path, mutation: str):
    plan = _plan()
    journal = replace(
        _journal(plan), native_execution_receipt_sha256=_d("8"), journal_sha256=None,
    )
    root = _workspace(tmp_path, plan, journal)
    caller = journal
    if mutation.startswith("caller"):
        caller = replace(
            journal,
            native_execution_receipt_sha256=None if mutation == "caller_omits" else _d("9"),
            journal_sha256=None,
        )
    else:
        durable = replace(journal, native_execution_receipt_sha256=_d("9"), journal_sha256=None)
        batch_journal = root / "evolution" / "producer-batches" / journal.journal_id / "journal.json"
        batch_journal.write_text(json.dumps(durable.to_dict(), sort_keys=True), encoding="utf-8")
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    # Both projections are individually valid and carry freshly recomputed self-digests.
    # That cannot authorize changing or omitting the original formal process receipt link.
    with pytest.raises(ProducerBundleRecoveryError, match="^producer_bundle_recovery_journal_mismatch$"):
        resume_producer_bundle_publication(root, plan, caller)
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_unknown_publication_marker_is_terminal(tmp_path: Path):
    plan = _plan()
    journal = _journal(plan)
    root = _workspace(tmp_path, plan, journal)
    payload = {
        "schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": journal.journal_id, "journal_sha256": journal.journal_sha256,
        "manifest_sha256": _d("e"), "status": "unknown",
    }
    marker = {**payload, "marker_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    (root / "evolution" / "producer-publication.json").write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    with pytest.raises(ProducerBundleRecoveryError) as caught:
        resume_producer_bundle_publication(root, plan, journal)
    assert caught.value.code == "producer_bundle_recovery_unknown_terminal"


def test_prepared_journal_is_not_resumed(tmp_path: Path):
    plan = _plan()
    journal = _journal(plan, state="prepared")
    root = _workspace(tmp_path, plan, journal)
    with pytest.raises(ProducerBundleRecoveryError) as caught:
        resume_producer_bundle_publication(root, plan, journal)
    assert caught.value.code == "producer_bundle_recovery_journal_state_invalid"


def test_published_resume_uses_terminal_and_final_journal(tmp_path: Path):
    plan = _plan()
    staged = _journal(plan)
    root = _workspace(tmp_path, plan, staged)
    batch = root / "evolution" / "producer-batches" / staged.journal_id
    cid = staged.candidates[0].candidate_id
    # The commit boundary retains journal.json as the publishing projection, moves the
    # candidate directory and writes an immutable published projection separately.
    admitted = replace(
        staged.candidates[0], execution_receipt_sha256=_d("8"), evaluation_receipt_sha256=_d("9"),
        publication_receipt_sha256=_d("c"), status="admitted",
    )
    publishing = build_producer_bundle_publication_journal(
        **{**staged.to_dict(), "journal_sha256": None, "candidates": (admitted,),
           "state": "publishing", "publication_phase": "staged"}
    )
    (batch / "journal.json").write_text(json.dumps(publishing.to_dict(), sort_keys=True), encoding="utf-8")
    final_root = root / "evolution" / "candidates" / cid
    final_root.mkdir(parents=True)
    for name in ("record.json", "receipt.json"):
        source = batch / "stage" / "candidates" / cid / name
        source.replace(final_root / name)
    stage_candidate = batch / "stage" / "candidates" / cid
    stage_candidate.rmdir()
    (batch / "stage" / "archive.jsonl").replace(root / "evolution" / "archive.jsonl")
    (batch / "stage" / "state.json").replace(root / "evolution" / "state.json")
    archive_after = hashlib.sha256((root / "evolution" / "archive.jsonl").read_bytes()).hexdigest()
    state_after = hashlib.sha256((root / "evolution" / "state.json").read_bytes()).hexdigest()
    payload = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    payload["journal_sha256"] = publishing.journal_sha256
    payload["archive_after_sha256"] = archive_after
    payload["state_after_sha256"] = state_after
    payload.pop("manifest_sha256")
    payload["manifest_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (batch / "manifest.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    terminal_payload = {
        "schema_version": "1", "protocol": "lunar-producer-bundle-publication-v1",
        "journal_id": staged.journal_id, "staged_journal_sha256": publishing.journal_sha256,
        "manifest_sha256": payload["manifest_sha256"], "archive_after_sha256": archive_after,
        "state_after_sha256": state_after, "status": "published",
    }
    terminal_sha = hashlib.sha256(json.dumps(terminal_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    terminal = {**terminal_payload, "terminal_marker_sha256": terminal_sha}
    (batch / "terminal.json").write_text(json.dumps(terminal, sort_keys=True), encoding="utf-8")
    final = build_producer_bundle_publication_journal(
        **{**publishing.to_dict(), "journal_sha256": None, "state": "published",
           "candidates": (admitted,),
           "publication_phase": "committed", "terminal_marker_sha256": terminal_sha,
           "archive_after_sha256": archive_after, "state_after_sha256": state_after}
    )
    (batch / "journal.published.json").write_text(json.dumps(final.to_dict(), sort_keys=True), encoding="utf-8")
    result = resume_producer_bundle_publication(root, plan, final)
    assert result.status == "published"

    (final_root / "record.json").write_bytes(b'{"candidate_id":"tampered"}\n')
    with pytest.raises(ProducerBundleRecoveryError, match="^producer_bundle_recovery_evidence_mismatch$"):
        resume_producer_bundle_publication(root, plan, final)
