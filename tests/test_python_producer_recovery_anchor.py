"""Recovery reads the original admission content without repairing lost proof."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_python_handoff_publication_pin import (
    _capture_stage,
    _replace_same_bytes,
    _run,
    _setup,
    _stage,
)

from lunar_evolution import producer_bundle_recovery as recovery
from lunar_evolution import producer_bundle_rejection as rejection
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import python_producer_admission_anchor as anchors
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationJournal,
    parse_producer_bundle_publication_journal,
)
from lunar_evolution.python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    build_python_producer_admission_handoff,
)

_ANCHOR_INVALID = "producer_bundle_recovery_python_admission_anchor_invalid"
_OUTCOMES = ("published", "all_rejected", "resume")
_AUTHORITY_NAMES = ("contract", "evaluator", "runner", "dependency", "environment")
_DRIFT_FIELDS = (
    "attempt_id", "run_id", "journal_id", "binding_sha256", "handoff_sha256",
    "terminal_sha256", "runtime_observation_sha256", "native_execution_receipt_sha256",
    "admission_plan_sha256", "request_budget", "wall_timeout_seconds", "deadline_unix",
    *("fingerprints." + name for name in _AUTHORITY_NAMES),
)


def _durable_snapshot(root: Path) -> dict[Path, tuple[object, ...]]:
    """Include names, identities and bytes, avoiding symlink/FIFO reads and atime."""
    result = {}
    for path in root.rglob("*"):
        info = path.lstat()
        identity = (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns,
        )
        content = (
            path.read_bytes() if stat.S_ISREG(info.st_mode)
            else os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
        )
        result[path.relative_to(root)] = (*identity, content)
    return result


def _retained_attempt(tmp_path: Path, monkeypatch, outcome: str):
    value = _setup(tmp_path, candidate_value=20 if outcome == "all_rejected" else 9)
    if outcome == "resume":
        captured = _capture_stage(value, monkeypatch)
        _stage(captured)
        journal = parse_producer_bundle_publication_journal(value.batch / "journal.json")
        assert journal.state == "publishing"
    else:
        journal = _run(value).terminal_journal
        assert journal.state == outcome
    return value, journal


def _forbid_reexecution(value: SimpleNamespace, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("recovery must not evaluate, publish or recreate an anchor")

    monkeypatch.setattr(value.context.bundle_pipeline, "evaluate_draft_non_publishing", forbidden)
    monkeypatch.setattr(transaction, "run_native_producer_bundle_publication_transaction", forbidden)
    monkeypatch.setattr(anchors, "persist_python_producer_admission_attempt_anchor", forbidden)


def _anchor_path(value: SimpleNamespace) -> Path:
    return value.batch / anchors.PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME


def _drift_anchor(path: Path, field: str) -> None:
    retained = anchors.read_python_producer_admission_attempt_anchor(path)
    if field.startswith("fingerprints."):
        fingerprints = dict(retained.fingerprints)
        name = field.split(".", 1)[1]
        fingerprints[name] = "c" * 64 if fingerprints[name] != "c" * 64 else "d" * 64
        changed = replace(retained, fingerprints=fingerprints, anchor_sha256=None)
    else:
        original = getattr(retained, field)
        replacement = (
            original + 1 if type(original) in {int, float}
            else ("c" * 64 if original != "c" * 64 else "d" * 64)
            if field.endswith("sha256") else original + "-drift"
        )
        changed = replace(retained, **{field: replacement}, anchor_sha256=None)
    path.write_bytes(changed.to_json())
    # This is a valid, self-consistent record; only independent retained authority refuses it.
    observed = anchors.read_python_producer_admission_attempt_anchor(path)
    assert observed.anchor_sha256 == changed.digest() != retained.anchor_sha256


def _resume(value: SimpleNamespace, journal: ProducerBundlePublicationJournal):
    return recovery.resume_producer_bundle_publication(value.context.workspace, value.plan, journal)


@pytest.mark.parametrize("outcome", _OUTCOMES)
def test_exact_recovery_reuses_all_retained_proof_readonly(tmp_path: Path, monkeypatch, outcome: str):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    retained = anchors.read_python_producer_admission_attempt_anchor(_anchor_path(value))
    assert retained.attempt_id == "attempt-" + value.handoff.handoff_sha256[:32]
    assert retained.journal_id == value.handoff.journal_id
    assert retained.run_id == value.handoff.run_id
    for field in (
        "binding_sha256", "handoff_sha256", "terminal_sha256", "runtime_observation_sha256",
        "native_execution_receipt_sha256", "admission_plan_sha256", "request_budget",
        "wall_timeout_seconds", "deadline_unix",
    ):
        assert getattr(retained, field) == getattr(value.handoff, field)
    assert retained.fingerprints == {
        name: getattr(value.handoff, name + "_sha256") for name in _AUTHORITY_NAMES
    }
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    result = _resume(value, journal)
    assert result.status == outcome
    assert result.journal_sha256 == journal.journal_sha256
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("outcome", _OUTCOMES)
@pytest.mark.parametrize("missing,error", [
    (anchors.PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME, _ANCHOR_INVALID),
    ("journal.prepared.json", "producer_bundle_recovery_python_handoff_invalid"),
    ("python-producer-admission-handoff.json", "producer_bundle_recovery_python_handoff_invalid"),
])
def test_missing_original_proof_refuses_without_recreation(
    tmp_path: Path, monkeypatch, outcome: str, missing: str, error: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    path = value.batch / missing
    path.unlink()
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == error
    assert not path.exists()
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("outcome", _OUTCOMES)
@pytest.mark.parametrize("field", _DRIFT_FIELDS)
def test_self_consistent_anchor_field_drift_is_not_adopted(
    tmp_path: Path, monkeypatch, outcome: str, field: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    _drift_anchor(_anchor_path(value), field)
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == _ANCHOR_INVALID
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("outcome", _OUTCOMES)
@pytest.mark.parametrize("form", [
    "malformed", "noncanonical", "digest", "symlink", "mode", "hardlink", "fifo", "oversize",
])
def test_unsafe_anchor_form_refuses_without_durable_effects(
    tmp_path: Path, monkeypatch, outcome: str, form: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    path = _anchor_path(value)
    if form == "malformed":
        path.write_bytes(b"{")
    elif form == "noncanonical":
        path.write_bytes(path.read_bytes() + b"\n")
    elif form == "digest":
        payload = json.loads(path.read_bytes())
        payload["anchor_sha256"] = "b" * 64
        path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    elif form == "symlink":
        retained = value.batch / "retained-admission-anchor.json"
        path.rename(retained)
        path.symlink_to(retained)
    elif form == "mode":
        path.chmod(0o644)
    elif form == "hardlink":
        os.link(path, value.batch / "admission-anchor-peer.json")
    elif form == "oversize":
        path.write_bytes(b" " * (anchors.MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES + 1))
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == _ANCHOR_INVALID
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("outcome,boundary", [
    ("published", "terminal"), ("published", "manifest"),
    ("all_rejected", "rejection"), ("resume", "manifest"), ("resume", "state-read"),
])
@pytest.mark.parametrize("mutation", ["missing", "drift"])
def test_final_return_rechecks_anchor_after_evidence_callbacks(
    tmp_path: Path, monkeypatch, outcome: str, boundary: str, mutation: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    _forbid_reexecution(value, monkeypatch)
    target, name = (
        (rejection, "inspect_producer_bundle_all_rejected") if boundary == "rejection"
        else (recovery, "_read" if boundary == "state-read"
              else "_terminal" if boundary == "terminal" else "_verify_manifest_files")
    )
    original = getattr(target, name)
    after_callback = []

    def mutate_after_inspection(*args, **kwargs):
        result = original(*args, **kwargs)
        if boundary == "state-read" and args[0] != value.batch / "stage/state.json":
            return result
        if mutation == "missing":
            _anchor_path(value).unlink()
        else:
            _drift_anchor(_anchor_path(value), "request_budget")
        after_callback.append(_durable_snapshot(value.context.workspace))
        return result

    monkeypatch.setattr(target, name, mutate_after_inspection)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == _ANCHOR_INVALID
    assert len(after_callback) == 1
    assert _durable_snapshot(value.context.workspace) == after_callback[0]


@pytest.mark.parametrize("outcome", _OUTCOMES)
@pytest.mark.parametrize("reader_call", [1, 2])
@pytest.mark.parametrize("mutation", ["handoff-replacement", "handoff-missing", "prepared-missing"])
def test_anchor_read_cannot_hide_original_handoff_or_prepared_link_drift(
    tmp_path: Path, monkeypatch, outcome: str, reader_call: int, mutation: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    _forbid_reexecution(value, monkeypatch)
    original = recovery.read_python_producer_admission_attempt_anchor
    calls = 0
    after_mutation = []

    def read_then_mutate(*args, **kwargs):
        nonlocal calls
        observed = original(*args, **kwargs)
        calls += 1
        if calls == reader_call:
            if mutation == "handoff-replacement":
                _replace_same_bytes(value.path)
            elif mutation == "handoff-missing":
                value.path.unlink()
            else:
                (value.batch / "journal.prepared.json").unlink()
            after_mutation.append(_durable_snapshot(value.context.workspace))
        return observed

    monkeypatch.setattr(recovery, "read_python_producer_admission_attempt_anchor", read_then_mutate)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == "producer_bundle_recovery_python_handoff_invalid"
    assert calls == reader_call and len(after_mutation) == 1
    assert _durable_snapshot(value.context.workspace) == after_mutation[0]


@pytest.mark.parametrize("outcome", _OUTCOMES)
def test_content_anchor_same_bytes_inode_replacement_remains_readonly(
    tmp_path: Path, monkeypatch, outcome: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    _replace_same_bytes(_anchor_path(value))
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    assert _resume(value, journal).status == outcome
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("outcome", _OUTCOMES)
def test_original_handoff_inode_replacement_still_refuses(
    tmp_path: Path, monkeypatch, outcome: str,
):
    value, journal = _retained_attempt(tmp_path, monkeypatch, outcome)
    _replace_same_bytes(value.path)
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == "producer_bundle_recovery_python_handoff_invalid"
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("pending,error", [
    ("prepared", "producer_bundle_recovery_journal_state_invalid"),
    ("unknown-marker", "producer_bundle_recovery_unknown_terminal"),
])
def test_pending_or_unknown_attempt_is_not_resumed_or_repaired(
    tmp_path: Path, monkeypatch, pending: str, error: str,
):
    value = _setup(tmp_path)
    captured = _capture_stage(value, monkeypatch)
    if pending == "prepared":
        prepared = value.batch / "journal.prepared.json"
        (value.batch / "journal.json").write_bytes(prepared.read_bytes())
        journal = parse_producer_bundle_publication_journal(prepared)
    else:
        _stage(captured)
        journal = parse_producer_bundle_publication_journal(value.batch / "journal.json")
        path = value.context.workspace / "evolution" / "producer-publication.json"
        marker = json.loads(path.read_bytes())
        marker.pop("marker_sha256")
        marker["status"] = "unknown"
        marker["marker_sha256"] = hashlib.sha256(
            json.dumps(marker, sort_keys=True, separators=(",", ":")).encode(),
        ).hexdigest()
        path.write_bytes(json.dumps(marker, sort_keys=True, separators=(",", ":")).encode())
    _forbid_reexecution(value, monkeypatch)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(recovery.ProducerBundleRecoveryError) as caught:
        _resume(value, journal)
    assert caught.value.code == error
    assert _durable_snapshot(value.context.workspace) == before


def test_projection_preserves_fractional_limits_and_independent_wire_digest(tmp_path: Path):
    value = _setup(tmp_path)
    payload = value.handoff.to_dict()
    payload.pop("handoff_sha256")
    payload.update(wall_timeout_seconds=60.375, deadline_unix=4102444800.125)
    handoff = build_python_producer_admission_handoff(payload)
    before = _durable_snapshot(value.context.workspace)
    projected = anchors.project_python_producer_admission_attempt_anchor(handoff)
    wire = {
        "schema_version": "1",
        "protocol": "lunar-python-producer-admission-attempt-anchor-v1",
        "attempt_id": "attempt-" + handoff.handoff_sha256[:32],
        "run_id": handoff.run_id, "journal_id": handoff.journal_id,
        "binding_sha256": handoff.binding_sha256, "handoff_sha256": handoff.handoff_sha256,
        "terminal_sha256": handoff.terminal_sha256,
        "runtime_observation_sha256": handoff.runtime_observation_sha256,
        "native_execution_receipt_sha256": handoff.native_execution_receipt_sha256,
        "admission_plan_sha256": handoff.admission_plan_sha256,
        "fingerprints": {name: getattr(handoff, name + "_sha256") for name in _AUTHORITY_NAMES},
        "request_budget": handoff.request_budget,
        "wall_timeout_seconds": 60.375, "deadline_unix": 4102444800.125,
    }
    wire["anchor_sha256"] = hashlib.sha256(
        json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
    assert projected.to_dict() == wire
    assert _durable_snapshot(value.context.workspace) == before


@pytest.mark.parametrize("form", ["mapping", "subclass", "duck-typed"])
def test_projection_refuses_nonexact_dto_without_invoking_untrusted_serializer(
    tmp_path: Path, form: str,
):
    value = _setup(tmp_path)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("untrusted serializer must not run")

    class HostileHandoff(PythonProducerAdmissionHandoff):
        def to_dict(self):
            return forbidden()

    candidate = (
        value.handoff.to_dict() if form == "mapping"
        else object.__new__(HostileHandoff) if form == "subclass"
        else SimpleNamespace(to_dict=forbidden)
    )
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(anchors.PythonProducerAdmissionAnchorError) as caught:
        anchors.project_python_producer_admission_attempt_anchor(candidate)
    assert caught.value.code == "python_producer_admission_anchor_handoff_invalid"
    assert calls == []
    assert _durable_snapshot(value.context.workspace) == before


def test_projection_does_not_resign_a_mutated_exact_dto(tmp_path: Path):
    value = _setup(tmp_path)
    retained_digest = value.handoff.handoff_sha256
    object.__setattr__(value.handoff, "request_budget", value.handoff.request_budget + 1)
    before = _durable_snapshot(value.context.workspace)
    with pytest.raises(anchors.PythonProducerAdmissionAnchorError) as caught:
        anchors.project_python_producer_admission_attempt_anchor(value.handoff)
    assert caught.value.code == "python_producer_admission_anchor_handoff_invalid"
    assert value.handoff.handoff_sha256 == retained_digest
    assert _durable_snapshot(value.context.workspace) == before
