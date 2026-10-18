"""Pure reserved C1/C2 observations; no producer, ledger or owner is invoked."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_producer_bundle_publication import _candidate, _journal
from test_rsi_brs_lineage_prefix import _sha, _wave

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import LineageSnapshotPin
from lunar_evolution.producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
)
from lunar_evolution.rsi_brs_lineage_prefix import (
    MAX_BRS_PREFIX_BYTES,
    validate_brs_reserved_prefix,
)
from lunar_evolution.rsi_brs_rejection_c1 import (
    REJECTION_SCHEMA,
    rejected_c1_entry,
    validate_rejected_c1_transition,
    validate_rejected_provenance_transition,
)
from lunar_evolution.rsi_brs_reserved_rejection import (
    MAX_RESERVED_REJECTION_BYTES,
    validate_reserved_brs_c1_transition,
    validate_reserved_brs_c2_transition,
    validate_reserved_brs_rejected_entry,
)
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_native_rejection import NativeRSIRejectionFilePin


def _pin(name, raw=b"", inode=9000):
    return LineageSnapshotPin(name, hashlib.sha256(raw).hexdigest(), len(raw), 7, inode, 7, 8000).to_dict()


def _p():
    return {"provenance_sha256": _sha("provenance-body"),
            "file_pin": NativeRSIRejectionFilePin("native-rsi.rejection-provenance.json", _sha("provenance-file"),
                                                 19, 7, 9500, 7, 8000).to_dict()}


def _base(batch, domain):
    return {"journal_id": batch["before"]["descriptor"]["journal_id"], "ordinal": batch["ordinal"],
            "episode_id": batch["episode_id"], "request_sha256": batch["request_sha256"],
            "memory_snapshot_sha256": domain["root_snapshot_sha256"], "native_plan_sha256": batch["native_plan_sha256"],
            "admission_plan": {}, "prepared_journal": {}, "before": deepcopy(batch["before"]["descriptor"]),
            "before_file_pin": deepcopy(batch["before"]["file_pin"]), "snapshots": deepcopy(batch["snapshots"]),
            "before_sources": {}, "state": "before", "evidence_pins": {}}


def _fixture(outcomes=(), *, candidates=1, active_candidates=None):
    domain, batches = _wave((*outcomes, "all_rejected"), candidates=candidates)
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:-1])
    old, index = [], []
    for batch in batches[:-1]:
        entry = _base(batch, domain)
        if batch["outcome"] == "published":
            entry.update(state="terminal", staged=deepcopy(batch["staged"]["descriptor"]),
                         staged_file_pin=deepcopy(batch["staged"]["file_pin"]),
                         state_projection_sha256=batch["snapshots"]["state-after"]["sha256"],
                         after_sources={}, terminal=deepcopy(batch["terminal"]["descriptor"]),
                         terminal_file_pin=deepcopy(batch["terminal"]["file_pin"]),
                         published_journal={}, head_sources={})
        else:
            entry.update(state="rejected", rejected=deepcopy(batch["terminal"]["descriptor"]),
                         rejected_file_pin=deepcopy(batch["terminal"]["file_pin"]), rejected_journal={},
                         rejection_provenance=_p(), rejection_schema=REJECTION_SCHEMA)
            index.append({"ordinal": batch["ordinal"], "journal_id": entry["journal_id"],
                          "rejected_sha256": entry["rejected"]["descriptor_sha256"]})
        old.append(entry)
    active = batches[-1]
    ordinal = len(old)
    before = _base(active, domain)
    current_candidates = candidates if active_candidates is None else active_candidates
    prepared = _journal(*(replace(_candidate(i), candidate_id=f"candidate-{ordinal}-{i}",
                                  bundle_id=f"bundle-{ordinal}-{i}", island_id=0,
                                  preparation_receipt_sha256=_sha(f"prepare-{ordinal}-{i}"))
                           for i in range(current_candidates)),
                        journal_id=before["journal_id"], run_id=domain["run_id"], task_id=before["episode_id"],
                        base_archive_sha256=before["before"]["archive"]["sha256"],
                        base_state_sha256=before["before"]["state"]["sha256"])
    rejected_journal = replace(prepared, candidates=tuple(replace(candidate, status="rejected",
        execution_receipt_sha256=_sha("execute-" + candidate.candidate_id),
        evaluation_receipt_sha256=_sha("evaluate-" + candidate.candidate_id))
        for candidate in prepared.candidates), state="all_rejected", publication_phase="committed",
        terminal_marker_sha256=_sha("marker"), archive_after_sha256=prepared.base_archive_sha256,
        state_after_sha256=prepared.base_state_sha256, journal_sha256=None)
    before["prepared_journal"] = prepared.to_dict()
    before["evidence_pins"] = {"journal.prepared.json": _pin("journal.prepared.json", canonical_json(prepared.to_dict()))}
    rejected = ProducerLineageRejectedTerminalV2(domain["run_id"], before["journal_id"], before["episode_id"], ordinal,
        before["before"]["descriptor_sha256"], prepared.digest(), rejected_journal.digest(), _sha("manifest"),
        rejected_journal.terminal_marker_sha256, tuple(candidate.candidate_id for candidate in prepared.candidates),
        prepared.base_archive_sha256, prepared.base_state_sha256)
    after = deepcopy(before)
    after.update(state="rejected", rejected=rejected.to_dict(), rejected_file_pin=_pin("rejected.json", rejected.to_json()),
                 rejected_journal=rejected_journal.to_dict(), rejection_provenance=None, rejection_schema=REJECTION_SCHEMA)
    for name in ("journal.json", "rejections.json", *("rejections/" + cid + ".json" for cid in rejected.candidate_ids)):
        pin_name = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
        after["evidence_pins"][name] = _pin(pin_name)
    published = prefix.published_predecessor
    head = dict(zip(("journal_id", "terminal_sha256", "lineage_sha256"), published, strict=True)) if published else None
    association = {"protocol": "lunar-rsi-brs-lineage-checkpoint-v1", "run_id": domain["run_id"],
                   "workspace": {"path": "/inert/workspace", "device": 7, "inode": 8},
                   "run_request_sha256": _sha("run-request"), "root_proof_sha256": _sha("root-proof"),
                   "policy_sha256": _sha("policy"), "max_batches": 8}
    original = {**association, "batches": deepcopy(old), "head": deepcopy(head), "rejections": deepcopy(index)}
    initial = {**deepcopy(original), "batches": [*deepcopy(old), before]}
    c1 = {**deepcopy(original), "batches": [*deepcopy(old), after], "rejections": [*deepcopy(index),
        {"ordinal": ordinal, "journal_id": rejected.journal_id, "rejected_sha256": rejected.digest()}]}
    c2 = deepcopy(c1)
    c2["batches"][-1]["rejection_provenance"] = _p()
    kwargs = {"prefix": prefix, "original_lineage_bytes": canonical_json(original) if old else None,
              "native_plan_sha256": active["native_plan_sha256"]}
    return initial, c1, c2, kwargs


@pytest.mark.parametrize("outcomes", [(), ("published",), ("all_rejected",), ("published", "all_rejected"),
                                     ("all_rejected", "published"), ("published", "all_rejected", "published")])
def test_genuine_descriptor_formats_keep_old_published_head_and_accumulated_rejection_index(outcomes):
    before, c1, c2, kwargs = _fixture(outcomes)
    saved = deepcopy((before, c1, c2))
    validate_reserved_brs_c1_transition(before, c1, **kwargs)
    validate_reserved_brs_c2_transition(c1, c2, **kwargs)
    assert (before, c1, c2) == saved
    assert c1["head"] == c2["head"] == before["head"]
    assert len(c2["rejections"]) == outcomes.count("all_rejected") + 1
    assert c2["batches"][-1]["ordinal"] == len(outcomes)
    assert c2["batches"][-1]["before"]["kind"] == ("before-v2" if outcomes else "before")
    if outcomes:
        with pytest.raises(RSILearningError):
            validate_rejected_c1_transition(before, c1)
        with pytest.raises(RSILearningError):
            validate_rejected_provenance_transition(c1, c2)
    else:
        rejected_c1_entry(c1["batches"][-1])
        validate_rejected_c1_transition(before, c1)
        validate_rejected_provenance_transition(c1, c2)


@pytest.mark.parametrize("field", ["ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256", "native_plan_sha256"])
def test_active_original_associations_cannot_drift(field):
    before, c1, _c2, kwargs = _fixture(("published",))
    value = True if field == "ordinal" else (_sha("wrong") if field.endswith("sha256") else "foreign-episode")
    c1["batches"][-1][field] = value
    with pytest.raises(RSILearningError):
        validate_reserved_brs_c1_transition(before, c1, **kwargs)


@pytest.mark.parametrize("axis", ["attempt", "published"])
def test_attempt_and_published_predecessor_axes_must_both_match_original_prefix(axis):
    before, c1, _c2, kwargs = _fixture(("published", "all_rejected"))
    entry = c1["batches"][-1]
    descriptor = ProducerLineageBeforeIntentV2.from_dict(entry["before"])
    field = "previous_attempt_terminal_sha256" if axis == "attempt" else "published_predecessor_terminal_sha256"
    descriptor = replace(descriptor, **{field: _sha("foreign-axis"), "descriptor_sha256": None})
    entry["before"], entry["before_file_pin"] = descriptor.to_dict(), _pin("before-v2.json", descriptor.to_json())
    rejected = replace(ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"]),
                       before_sha256=descriptor.digest(), descriptor_sha256=None)
    entry["rejected"], entry["rejected_file_pin"] = rejected.to_dict(), _pin("rejected.json", rejected.to_json())
    with pytest.raises(RSILearningError, match="predecessor_drift"):
        validate_reserved_brs_c1_transition(before, c1, **kwargs)


@pytest.mark.parametrize("fault", ["head", "index", "old_bytes", "old_pin", "association", "original_noncanonical",
                                  "missing_original", "extra_batch", "before_prepared_pin", "old_prefix_refreshed",
                                  "old_staged_refreshed", "old_c2_cleared"])
def test_original_historical_bytes_head_index_and_only_active_delta_are_immutable(fault):
    before, c1, _c2, kwargs = _fixture(("published", "all_rejected"))
    if fault == "head":
        before["head"] = c1["head"] = None
    elif fault == "index":
        c1["rejections"] = c1["rejections"][-1:]
    elif fault == "old_bytes":
        c1["batches"][0]["prepared_journal"] = {"foreign": 1}
    elif fault == "old_pin":
        c1["batches"][0]["terminal_file_pin"]["inode"] += 1
    elif fault == "association":
        before["policy_sha256"] = c1["policy_sha256"] = _sha("foreign-policy")
    elif fault == "original_noncanonical":
        kwargs["original_lineage_bytes"] += b"\n"
    elif fault == "missing_original":
        kwargs["original_lineage_bytes"] = None
    elif fault == "extra_batch":
        c1["batches"].append(deepcopy(c1["batches"][-1]))
    elif fault == "before_prepared_pin":
        before["batches"][-1]["evidence_pins"]["journal.prepared.json"]["inode"] += 1
    elif fault == "old_prefix_refreshed":
        original = json.loads(kwargs["original_lineage_bytes"])
        for wire in (original, before, c1):
            wire["batches"][0]["terminal_file_pin"]["inode"] += 1
        kwargs["original_lineage_bytes"] = canonical_json(original)
    elif fault == "old_staged_refreshed":
        original = json.loads(kwargs["original_lineage_bytes"])
        for wire in (original, before, c1):
            wire["batches"][0]["staged_file_pin"]["inode"] += 1
        kwargs["original_lineage_bytes"] = canonical_json(original)
    else:
        original = json.loads(kwargs["original_lineage_bytes"])
        for wire in (original, before, c1):
            wire["batches"][1]["rejection_provenance"] = None
        kwargs["original_lineage_bytes"] = canonical_json(original)
    with pytest.raises(RSILearningError):
        validate_reserved_brs_c1_transition(before, c1, **kwargs)


@pytest.mark.parametrize("fault", ["replay", "clear", "wrong_pin", "wrong_digest", "index", "other_active", "old_prefix"])
def test_c2_is_only_original_null_to_present_reference_delta(fault):
    _before, c1, c2, kwargs = _fixture(("published", "all_rejected"))
    if fault == "replay":
        c1 = deepcopy(c2)
    elif fault == "clear":
        c2["batches"][-1]["rejection_provenance"] = None
    elif fault == "wrong_pin":
        c2["batches"][-1]["rejection_provenance"]["file_pin"]["mode"] = 0o600
    elif fault == "wrong_digest":
        c2["batches"][-1]["rejection_provenance"]["provenance_sha256"] = True
    elif fault == "index":
        c2["rejections"] = []
    elif fault == "other_active":
        c2["batches"][-1]["before_sources"]["foreign"] = 1
    else:
        c2["batches"][0]["published_journal"]["foreign"] = 1
    with pytest.raises(RSILearningError):
        validate_reserved_brs_c2_transition(c1, c2, **kwargs)


@pytest.mark.parametrize("value", [0, 1, None, "yes", [], {}])
def test_provenance_switch_requires_exact_bool(value):
    _before, c1, _c2, kwargs = _fixture()
    with pytest.raises(RSILearningError):
        validate_reserved_brs_rejected_entry(c1["batches"][-1], prefix=kwargs["prefix"],
                                             native_plan_sha256=kwargs["native_plan_sha256"], with_provenance=value)


@pytest.mark.parametrize("fault", ["dict_subclass", "nested_subclass", "prefix_member", "oversized_prefix", "oversized_original",
                                  "deep", "oversized_wire", "genesis_original"])
def test_strict_bounded_inputs_refuse_before_foreign_hooks(fault):
    before, c1, _c2, kwargs = _fixture(("all_rejected",))

    class Foreign(dict):
        def __iter__(self):
            pytest.fail("foreign iteration executed")

        def __eq__(self, other):
            pytest.fail("foreign equality executed")

        def values(self):
            pytest.fail("foreign values executed")

    if fault == "dict_subclass":
        c1 = Foreign(c1)
    elif fault == "nested_subclass":
        c1["batches"][-1]["evidence_pins"] = Foreign(c1["batches"][-1]["evidence_pins"])
    elif fault == "prefix_member":
        object.__setattr__(kwargs["prefix"], "batch_bytes", (Foreign(),))
    elif fault == "oversized_prefix":
        object.__setattr__(kwargs["prefix"], "canonical_bytes", b"x" * (MAX_BRS_PREFIX_BYTES + 1))
    elif fault == "oversized_original":
        kwargs["original_lineage_bytes"] = b"x" * (MAX_RESERVED_REJECTION_BYTES + 1)
    elif fault == "deep":
        value = None
        for _ in range(34):
            value = {"nested": value}
        c1["batches"][-1]["before_sources"] = value
    elif fault == "oversized_wire":
        c1["batches"][-1]["before_sources"] = {"large": "x" * MAX_RESERVED_REJECTION_BYTES}
    else:
        before, c1, _c2, kwargs = _fixture()
        kwargs["original_lineage_bytes"] = b"{}"
    with pytest.raises(RSILearningError):
        validate_reserved_brs_c1_transition(before, c1, **kwargs)


def test_pure_validators_do_not_open_files_or_connect_ledger(monkeypatch):
    import builtins
    import sqlite3

    before, c1, c2, kwargs = _fixture(("published", "all_rejected"))

    def forbidden(*_args, **_kwargs):
        pytest.fail("pure reserved rejection validator attempted IO")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    validate_reserved_brs_c1_transition(before, c1, **kwargs)
    validate_reserved_brs_c2_transition(c1, c2, **kwargs)


def test_eighth_child_and_exactly_thirty_two_candidates_fit_original_limits():
    before, c1, c2, kwargs = _fixture(("published", "all_rejected") * 3 + ("published",), candidates=4)
    validate_reserved_brs_c1_transition(before, c1, **kwargs)
    validate_reserved_brs_c2_transition(c1, c2, **kwargs)
    assert c1["batches"][-1]["ordinal"] == 7


def test_thirty_third_candidate_refuses_before_any_transition():
    before, c1, _c2, kwargs = _fixture(("published", "all_rejected") * 3 + ("published",),
                                      candidates=4, active_candidates=5)
    with pytest.raises(RSILearningError, match="association_drift"):
        validate_reserved_brs_c1_transition(before, c1, **kwargs)


@pytest.mark.parametrize("field", ["prepared_journal", "rejected_journal"])
def test_journal_wire_cannot_select_a_filesystem_parser_path(monkeypatch, field):
    from pathlib import Path

    _before, c1, _c2, kwargs = _fixture()
    c1["batches"][-1][field] = "/inert/not-a-journal-wire.json"

    def forbidden(*_args, **_kwargs):
        pytest.fail("string journal selected a filesystem parser")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(RSILearningError, match="entry_invalid"):
        validate_reserved_brs_rejected_entry(c1["batches"][-1], prefix=kwargs["prefix"],
                                             native_plan_sha256=kwargs["native_plan_sha256"])
