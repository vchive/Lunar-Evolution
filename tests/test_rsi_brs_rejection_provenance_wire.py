"""Detached strict C1/C2 observations grant no owner, file or claim authority."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_native_rejection import digest, rejection_evidence

from lunar_evolution import rsi_brs_rejection_c1 as rejection
from lunar_evolution.producer_bundle_lineage import LineageSnapshotPin, ProducerLineageBeforeIntent
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_rejection import (
    MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES,
    NativeRSIRejectionFilePin,
)


def _pin(name, inode, *, sha256="a" * 64, size=3):
    return LineageSnapshotPin(name, sha256, size, 1, inode, 1, 1000,
                              mtime_ns=10, ctime_ns=11)


def _wires(count=2):
    """Build associated finite DTOs without a ledger, filesystem or owner shell."""
    evidence = rejection_evidence(count=count)
    terminal = evidence.terminal
    before = ProducerLineageBeforeIntent(
        terminal.run_id, terminal.journal_id, 0, None, None,
        _pin("archive-before.snapshot", 1, sha256=terminal.base_archive_sha256, size=9),
        _pin("state-before.snapshot", 2, sha256=terminal.base_state_sha256, size=11),
    )
    prepared = replace(terminal, candidates=tuple(replace(
        item, execution_receipt_sha256=None, evaluation_receipt_sha256=None, status="planned",
    ) for item in terminal.candidates), state="prepared", publication_phase="preflight",
        terminal_marker_sha256=None, archive_after_sha256=None, state_after_sha256=None,
        journal_sha256=None)
    rejected = replace(evidence.rejected, before_sha256=before.digest(),
                       prepared_journal_sha256=prepared.digest(), descriptor_sha256=None)
    pins = {"journal.prepared.json": _pin("journal.prepared.json", 11, size=5).to_dict(),
            "journal.json": _pin("journal.json", 12).to_dict(),
            "rejections.json": _pin("rejections.json", 13).to_dict()}
    for index, candidate_id in enumerate(rejected.candidate_ids):
        name = "rejections/" + candidate_id + ".json"
        pins[name] = _pin("rejection-" + hashlib.sha256(name.encode()).hexdigest(),
                          20 + index).to_dict()
    entry = {
        "journal_id": terminal.journal_id, "ordinal": 0, "episode_id": evidence.plan.request.episode_id,
        "request_sha256": evidence.plan.request_sha256,
        "memory_snapshot_sha256": evidence.plan.request.memory_snapshot_sha256,
        "native_plan_sha256": evidence.plan.plan_sha256, "admission_plan": {},
        "prepared_journal": prepared.to_dict(), "before": before.to_dict(),
        "before_file_pin": _pin("before.json", 3, sha256=hashlib.sha256(before.to_json()).hexdigest(),
                                size=len(before.to_json())).to_dict(),
        "snapshots": {"archive-before": before.archive.to_dict(), "state-before": before.state.to_dict()},
        "before_sources": {}, "state": "rejected", "evidence_pins": pins,
        "rejected": rejected.to_dict(),
        "rejected_file_pin": _pin("rejected.json", 4, sha256=hashlib.sha256(rejected.to_json()).hexdigest(),
                                  size=len(rejected.to_json())).to_dict(),
        "rejected_journal": terminal.to_dict(), "rejection_provenance": None,
        "rejection_schema": rejection.REJECTION_SCHEMA,
    }
    c1 = {"protocol": "lunar-rsi-brs-lineage-checkpoint-v1", "run_id": terminal.run_id,
          "workspace": {"path": "/fixture"}, "batches": [entry], "head": None,
          "rejections": rejection.rejected_c1_index(entry), "budget": {"executions": 0}}
    c2 = deepcopy(c1)
    c2["batches"][0]["rejection_provenance"] = {
        "provenance_sha256": digest("native-body"),
        "file_pin": NativeRSIRejectionFilePin(
            "native-rsi.rejection-provenance.json", digest("complete-file"), 64,
            1, 900, 1, 1000, mtime_ns=10, ctime_ns=11,
        ).to_dict(),
    }
    return c1, c2


@pytest.mark.parametrize("count", [1, 2])
def test_c2_is_pure_detached_and_preserves_c1_descriptor_and_index(count, monkeypatch):
    c1, c2 = _wires(count)
    original = deepcopy((c1, c2))
    monkeypatch.setattr("pathlib.Path.stat", lambda *_args, **_kwargs: pytest.fail("parser read disk"))
    monkeypatch.setattr("pathlib.Path.lstat", lambda *_args, **_kwargs: pytest.fail("parser read disk"))
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: pytest.fail("parser read disk"))
    parsed = rejection.rejected_provenance_entry(c2["batches"][0])
    assert parsed.to_dict() == c1["batches"][0]["rejected"]
    assert rejection.rejected_provenance_index(c2["batches"][0]) == c1["rejections"]
    rejection.validate_rejected_provenance_transition(c1, c2)
    assert (c1, c2) == original


def test_body_digest_and_complete_file_hash_are_independent_and_c1_stays_null_only():
    c1, c2 = _wires()
    reference = c2["batches"][0]["rejection_provenance"]
    assert reference["provenance_sha256"] != reference["file_pin"]["sha256"]
    rejection.rejected_provenance_entry(c2["batches"][0])
    with pytest.raises(RSILearningError, match="shape_invalid"):
        rejection.rejected_c1_entry(c2["batches"][0])
    with pytest.raises(RSILearningError, match="provenance_invalid"):
        rejection.rejected_provenance_entry(c1["batches"][0])


@pytest.mark.parametrize("digest_value", [None, True, 4, "A" * 64, "x" * 64, "a" * 63, "a" * 65])
def test_c2_refuses_malformed_body_digest(digest_value):
    _c1, c2 = _wires()
    c2["batches"][0]["rejection_provenance"]["provenance_sha256"] = digest_value
    with pytest.raises(RSILearningError, match="provenance_invalid"):
        rejection.rejected_provenance_entry(c2["batches"][0])


@pytest.mark.parametrize("mutation", ["missing", "extra", "list", "null"])
def test_c2_reference_has_exact_fields(mutation):
    _c1, c2 = _wires()
    entry = c2["batches"][0]
    reference = entry["rejection_provenance"]
    if mutation == "missing":
        reference.pop("file_pin")
    elif mutation == "extra":
        reference["permission"] = True
    else:
        entry["rejection_provenance"] = [] if mutation == "list" else None
    with pytest.raises(RSILearningError, match="provenance_invalid"):
        rejection.rejected_provenance_entry(entry)


@pytest.mark.parametrize("field,value", [
    ("name", "foreign.json"), ("sha256", "bad"), ("size", 0), ("size", True),
    ("size", MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES + 1), ("inode", 0),
    ("parent_inode", 0), ("mode", 0o600), ("nlink", 2), ("mtime_ns", -1),
    ("device", 2**64), ("ctime_ns", True),
])
def test_c2_requires_strict_native_file_pin(field, value):
    _c1, c2 = _wires()
    c2["batches"][0]["rejection_provenance"]["file_pin"][field] = value
    with pytest.raises(ValueError):
        rejection.rejected_provenance_entry(c2["batches"][0])


@pytest.mark.parametrize("mutation", [
    "budget", "root-key", "protocol", "head", "missing-head", "index", "duplicate-batch", "ordinal",
    "request", "memory", "plan", "admission", "source", "evidence-pin", "schema",
])
def test_transition_refuses_every_other_root_or_entry_change(mutation):
    c1, c2 = _wires()
    entry = c2["batches"][0]
    if mutation == "budget":
        c2["budget"]["executions"] += 1
    elif mutation == "root-key":
        c2["extra"] = "unpermitted"
    elif mutation == "protocol":
        c1["protocol"] = c2["protocol"] = "foreign"
    elif mutation == "head":
        c2["head"] = {"published": "invented"}
    elif mutation == "missing-head":
        c1.pop("head")
        c2.pop("head")
    elif mutation == "index":
        c2["rejections"][0]["rejected_sha256"] = digest("different")
    elif mutation == "duplicate-batch":
        c2["batches"].append(deepcopy(entry))
    elif mutation == "ordinal":
        entry["ordinal"] = True
    elif mutation in {"request", "memory", "plan"}:
        field = {"request": "request_sha256", "memory": "memory_snapshot_sha256",
                 "plan": "native_plan_sha256"}[mutation]
        entry[field] = digest("different")
    elif mutation == "admission":
        entry["admission_plan"]["changed"] = True
    elif mutation == "source":
        entry["before_sources"]["changed"] = True
    elif mutation == "evidence-pin":
        entry["evidence_pins"]["journal.json"]["inode"] += 1
    else:
        entry["rejection_schema"] = rejection.REJECTION_PROVENANCE_SCHEMA
    with pytest.raises((RSILearningError, ValueError)):
        rejection.validate_rejected_provenance_transition(c1, c2)


def test_transition_is_single_use_and_cannot_replace_existing_provenance():
    c1, c2 = _wires()
    for before, after in ((c1, c1), (c2, c2), (c2, c1)):
        with pytest.raises(RSILearningError):
            rejection.validate_rejected_provenance_transition(before, after)
    changed = deepcopy(c2)
    changed["batches"][0]["rejection_provenance"]["file_pin"]["inode"] += 1
    with pytest.raises(RSILearningError):
        rejection.validate_rejected_provenance_transition(c2, changed)


@pytest.mark.parametrize("mutation", ["dict", "key", "value", "cycle"])
def test_plain_shape_gate_refuses_callbacks_and_cycles_before_comparison(mutation):
    class Dangerous(dict):
        def items(self):
            pytest.fail("called foreign mapping method")

    class DangerousString(str):
        __hash__ = str.__hash__

        def __eq__(self, _other):
            pytest.fail("called foreign string equality")

    c1, c2 = _wires()
    entry = c2["batches"][0]
    reference = entry["rejection_provenance"]
    if mutation == "dict":
        entry["rejection_provenance"] = Dangerous(reference)
    elif mutation == "key":
        entry["rejection_provenance"] = {DangerousString("file_pin"): reference["file_pin"]}
    elif mutation == "value":
        reference["provenance_sha256"] = DangerousString(reference["provenance_sha256"])
    else:
        reference["cycle"] = reference
    for call in (
        lambda: rejection.rejected_provenance_entry(entry),
        lambda: rejection.rejected_provenance_index(entry),
        lambda: rejection.validate_rejected_provenance_transition(c1, c2),
    ):
        with pytest.raises(ValueError, match="shape"):
            call()
