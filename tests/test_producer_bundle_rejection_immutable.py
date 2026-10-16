"""Native rejection evidence with only the lowest process/evaluator seam inert."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_producer_bundle_publication import _journal
from test_producer_bundle_rejection import _rejected
from test_producer_bundle_transaction_control import _fixture

from lunar_evolution import candidate_evaluation, candidate_execution_runner
from lunar_evolution import producer_bundle_rejection as rejection
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_preflight import (
    ProducerBundlePreflightReceipt,
    _authority_digest,
)
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationJournal
from lunar_evolution.producer_bundle_receipts import ProducerBundleEvaluationReceipt
from lunar_evolution.producer_bundle_rejection import (
    ProducerBundleRejectionError,
    VerifiedProducerBundleRejection,
    _verify_terminal_batch_rejection_evidence,
    inspect_producer_bundle_all_rejected,
)
from lunar_evolution.producer_bundle_transaction import (
    run_native_producer_bundle_publication_transaction,
)


def _inert_fixture_process(command, *, cwd, process_observer=None, process_released=None,
                           process_exit_observed=None, continuation_guard=None, **_kwargs):
    """Return the known local fixture output while retaining native receipt writes."""
    if continuation_guard is not None:
        continuation_guard()
    if process_observer is not None:
        process_observer(4242, 4242)
    root = Path(cwd)
    if "evaluator.py" in command:
        value = json.loads((root / "output/result.json").read_bytes())["value"]
        limit = int((root / "inputs/value").read_text())
        valid = int(type(value) is int and 0 <= value <= limit)
        stdout = canonical_json({
            "schema_version": "1", "evaluator_id": "bundle-population-fixture",
            "validity": valid, "quality": float(value) if valid else None,
            "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
            "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value exceeds the input limit."}],
        })
    else:
        source = (root / command[-1]).read_text()
        match = re.search(r"^value = ([0-9]+)$", source, re.MULTILINE)
        assert match is not None, "only the fixed value fixture is allowed"
        (root / "output").mkdir(exist_ok=True)
        (root / "output/result.json").write_bytes(canonical_json({"value": int(match.group(1))}))
        stdout = b""
    if process_exit_observed is not None:
        process_exit_observed(0)
    if process_released is not None:
        process_released(4242, 4242)
    if continuation_guard is not None:
        continuation_guard()
    return stdout, b"", "succeeded", 0, None


@pytest.fixture(autouse=True)
def inert_native_process_boundary(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("process/network execution is forbidden in the immutable helper suite")

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", _inert_fixture_process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_fixture_process)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _pure_journals():
    prepared = _journal()
    candidate = replace(prepared.candidates[0], status="rejected", execution_receipt_sha256="8" * 64,
                        evaluation_receipt_sha256="9" * 64)
    terminal = replace(prepared, state="all_rejected", publication_phase="committed", candidates=(candidate,),
                       terminal_marker_sha256="a" * 64, archive_after_sha256=prepared.base_archive_sha256,
                       state_after_sha256=prepared.base_state_sha256, journal_sha256=None)
    return prepared, terminal


def _observe_fixture(tmp_path, values=(999, 998)):
    context, strategy, drafts, plan, journal_id = _fixture(tmp_path, values)
    result = run_native_producer_bundle_publication_transaction(
        context.workspace, strategy, drafts, plan, journal_id=journal_id,
    )
    assert result.publication_status == "all_rejected"
    batch = context.workspace / "evolution/producer-batches" / journal_id
    return context, result, batch


def _inspect(context, result, batch, *, terminal=None):
    return _verify_terminal_batch_rejection_evidence(
        context.workspace, batch, result.journal,
        terminal=result.terminal_journal if terminal is None else terminal, preflight=result.preflight,
    )


def _rehash_manifest(batch, terminal, manifest):
    payload = {key: value for key, value in manifest.items() if key != "terminal_marker_sha256"}
    marker = hashlib.sha256(rejection._canonical(payload)).hexdigest()
    manifest["terminal_marker_sha256"] = marker
    (batch / "rejections.json").write_bytes(rejection._pretty(manifest, rejection._MAX_BYTES))
    changed = replace(terminal, terminal_marker_sha256=marker, journal_sha256=None)
    (batch / "journal.json").write_bytes(rejection._pretty(changed.to_dict(), rejection._MAX_BYTES))
    return changed


def test_complete_ordered_multi_candidate_native_observation_and_distinct_manifest_sha(tmp_path):
    context, result, batch = _observe_fixture(tmp_path)
    observed = _inspect(context, result, batch)
    assert type(observed) is VerifiedProducerBundleRejection
    assert observed.terminal == result.terminal_journal
    assert observed.candidate_ids == tuple(item.candidate_id for item in result.journal.candidates)
    assert len(observed.candidate_ids) == len(observed.execution_receipt_sha256s) == len(observed.evaluation_receipt_sha256s) == len(observed.retained_evidence_sha256s) == 2
    assert observed.manifest_sha256 == hashlib.sha256((batch / "rejections.json").read_bytes()).hexdigest()
    assert observed.manifest_sha256 != observed.terminal.terminal_marker_sha256
    assert observed.execution_receipt_sha256s == tuple(item.execution_receipt_sha256 for item in observed.terminal.candidates)
    assert observed.evaluation_receipt_sha256s == tuple(item.evaluation_receipt_sha256 for item in observed.terminal.candidates)
    assert observed.retained_evidence_sha256s == tuple(json.loads((batch / "rejections" / f"{candidate}.json").read_bytes())["retained_evidence"]["evidence_sha256"] for candidate in observed.candidate_ids)
    assert all(item.publication_receipt_sha256 is None for item in observed.terminal.candidates)
    with pytest.raises(FrozenInstanceError):
        observed.manifest_sha256 = "b" * 64


def test_immutable_history_accepts_later_live_head_but_public_reader_keeps_prefix_gate(tmp_path):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    original = _inspect(context, result, batch)
    evolution = context.workspace / "evolution"
    (evolution / "archive.jsonl").write_bytes(b"later published archive\n")
    (evolution / "state.json").write_bytes(b"later published state\n")
    assert _inspect(context, result, batch) == original
    with pytest.raises(ProducerBundleRejectionError, match="prefix_drift"):
        inspect_producer_bundle_all_rejected(context.workspace, result.journal)


def test_immutable_history_accepts_other_staged_marker_but_public_reader_refuses(tmp_path):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    original = _inspect(context, result, batch)
    (context.workspace / "evolution/producer-publication.json").write_bytes(b"original next staged marker")
    assert _inspect(context, result, batch) == original
    with pytest.raises(ProducerBundleRejectionError, match="recovery_required"):
        inspect_producer_bundle_all_rejected(context.workspace, result.journal)


def test_rejected_final_candidate_absence_is_still_checked_under_later_head(tmp_path):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    (context.workspace / "evolution/state.json").write_bytes(b"later head")
    candidate = result.journal.candidates[0].candidate_id
    (context.workspace / "evolution/candidates" / candidate).mkdir()
    with pytest.raises(ProducerBundleRejectionError, match="candidate_conflict"):
        _inspect(context, result, batch)


@pytest.mark.parametrize("name", ["stage", "manifest.json", "journal.staged.json", "journal.published.json", "terminal.json"])
def test_immutable_reader_refuses_own_publication_artifacts(tmp_path, name):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    (batch / name).write_bytes(b"conflict")
    with pytest.raises(ProducerBundleRejectionError, match="recovery_required"):
        _inspect(context, result, batch)


@pytest.mark.parametrize("mutation", ["order", "cardinality", "candidate_order", "extra_file", "noncanonical"])
def test_complete_manifest_order_cardinality_directory_and_bytes_required(tmp_path, mutation):
    context, result, batch = _observe_fixture(tmp_path)
    manifest = json.loads((batch / "rejections.json").read_bytes())
    terminal = result.terminal_journal
    if mutation == "extra_file":
        (batch / "rejections/extra.json").write_bytes(b"extra")
    elif mutation == "noncanonical":
        (batch / "rejections.json").write_bytes(json.dumps(manifest).encode())
    else:
        if mutation == "order":
            manifest["entries"].reverse()
        elif mutation == "cardinality":
            manifest["entries"].pop()
        else:
            manifest["candidate_ids"].reverse()
        terminal = _rehash_manifest(batch, terminal, manifest)
    with pytest.raises(ProducerBundleRejectionError):
        _inspect(context, result, batch, terminal=terminal)


def test_rehashed_receipt_still_must_equal_original_native_receipt(tmp_path):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    candidate = result.journal.candidates[0].candidate_id
    relative = "rejections/" + candidate + ".json"
    path = batch / relative
    record = json.loads(path.read_bytes())
    evaluation = ProducerBundleEvaluationReceipt.from_dict(record["evaluation_receipt"])
    record["evaluation_receipt"] = replace(evaluation, evaluation_sha256="a" * 64, receipt_sha256=None).to_dict()
    raw = rejection._pretty(record, rejection._MAX_BYTES)
    path.write_bytes(raw)
    manifest = json.loads((batch / "rejections.json").read_bytes())
    manifest["entries"][0] = rejection._file_descriptor(path, relative, raw)
    terminal = _rehash_manifest(batch, result.terminal_journal, manifest)
    with pytest.raises(ProducerBundleRejectionError, match="receipt_mismatch"):
        _inspect(context, result, batch, terminal=terminal)


def test_exact_preflight_and_terminal_association_required(tmp_path):
    context, result, batch = _observe_fixture(tmp_path, (999,))
    changed = replace(result.terminal_journal, terminal_marker_sha256="a" * 64, journal_sha256=None)
    with pytest.raises(ProducerBundleRejectionError, match="journal_mismatch"):
        _inspect(context, result, batch, terminal=changed)
    other = replace(result.preflight, record_count=result.preflight.record_count + 1, receipt_sha256=None)
    with pytest.raises(ProducerBundleRejectionError, match="preflight_mismatch"):
        _verify_terminal_batch_rejection_evidence(context.workspace, batch, result.journal,
                                                terminal=result.terminal_journal, preflight=other)


@pytest.mark.parametrize("mutation", ["missing_terminal", "missing_manifest", "missing_records", "source", "record_inode", "intent_inode"])
def test_original_native_material_remains_required(tmp_path, mutation):
    context, _strategy, _drafts, _plan, result, terminal, batch, _before = _rejected(tmp_path)
    if mutation == "missing_terminal":
        (batch / "journal.json").unlink()
    elif mutation == "missing_manifest":
        (batch / "rejections.json").unlink()
    elif mutation == "missing_records":
        (batch / "rejections" / f"{terminal.candidates[0].candidate_id}.json").unlink()
    elif mutation == "source":
        path = result.evaluations[0].source_root / result.evaluations[0].bundle.entrypoint
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    else:
        path = batch / ("journal.prepared.json" if mutation == "intent_inode" else f"rejections/{terminal.candidates[0].candidate_id}.json")
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    with pytest.raises(ProducerBundleRejectionError):
        _verify_terminal_batch_rejection_evidence(context.workspace, batch, result.journal, terminal=terminal)


@pytest.mark.parametrize("target,field,value", [
    ("prepared", "candidates", []), ("prepared", "num_islands", True),
    ("terminal", "candidate_id", object()), ("terminal", "python_handoff_file_pin", {}),
    ("terminal", "terminal_marker_sha256", None),
])
def test_exact_nested_shape_validation_precedes_io(tmp_path, monkeypatch, target, field, value):
    prepared, terminal = _pure_journals()
    dto = prepared if target == "prepared" else terminal
    if field == "candidate_id":
        dto = dto.candidates[0]
    object.__setattr__(dto, field, value)

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid DTO must be refused before filesystem observation")

    monkeypatch.setattr(rejection, "DirectoryChain", forbidden)
    with pytest.raises(ProducerBundleRejectionError):
        _verify_terminal_batch_rejection_evidence(tmp_path, tmp_path / "batch", prepared, terminal=terminal)
    assert list(tmp_path.iterdir()) == []


def test_callbacks_subclasses_and_foreign_batch_refused_before_io(tmp_path, monkeypatch):
    prepared, terminal = _pure_journals()

    class Trap:
        def __fspath__(self):
            pytest.fail("path callback")

        def to_dict(self):
            pytest.fail("DTO callback")

    def forbidden(*_args, **_kwargs):
        pytest.fail("foreign/invalid input must be refused before filesystem observation")

    monkeypatch.setattr(rejection, "DirectoryChain", forbidden)
    for root, batch, journal in [(Trap(), tmp_path, prepared), (tmp_path, Trap(), prepared), (tmp_path, tmp_path, Trap()), (tmp_path, tmp_path / "foreign", prepared)]:
        with pytest.raises(ProducerBundleRejectionError):
            _verify_terminal_batch_rejection_evidence(root, batch, journal, terminal=terminal)
    raw = {field: getattr(prepared, field) for field in prepared.__dataclass_fields__}
    class ForeignJournal(ProducerBundlePublicationJournal):
        def to_dict(self, **_kwargs):
            pytest.fail("subclass callback")

    # Bypass subclass initialization; the private verifier must reject its exact type.
    foreign = object.__new__(ForeignJournal)
    for field, value in raw.items():
        object.__setattr__(foreign, field, value)
    with pytest.raises(ProducerBundleRejectionError):
        _verify_terminal_batch_rejection_evidence(tmp_path, tmp_path, foreign, terminal=terminal)


def test_preflight_shape_refuses_nested_callback_before_io(tmp_path, monkeypatch):
    prepared, terminal = _pure_journals()
    preflight = ProducerBundlePreflightReceipt(
        journal_id=prepared.journal_id, run_id=prepared.run_id, task_id=prepared.task_id,
        plan_sha256=prepared.admission_sha256, archive_prefix_sha256=prepared.archive_prefix_sha256,
        base_archive_sha256=prepared.base_archive_sha256, base_state_sha256=prepared.base_state_sha256,
        authority_sha256=_authority_digest(prepared), candidate_ids=(prepared.candidates[0].candidate_id,),
        record_count=0, workspace_relative="evolution/producer-batches/" + prepared.journal_id,
    )
    object.__setattr__(preflight, "candidate_ids", (object(),))
    monkeypatch.setattr(rejection, "DirectoryChain", lambda *_args: pytest.fail("shape validation must precede I/O"))
    with pytest.raises(ProducerBundleRejectionError):
        _verify_terminal_batch_rejection_evidence(tmp_path, tmp_path, prepared, terminal=terminal, preflight=preflight)
