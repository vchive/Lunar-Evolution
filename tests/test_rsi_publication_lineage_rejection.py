"""Pure v2 history/capacity gates and original inert native rejection evidence."""

from __future__ import annotations

import copy
import socket
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_producer_bundle_publication import _candidate, _journal
from test_producer_bundle_rejection_immutable import _inert_fixture_process
from test_producer_bundle_transaction_control import _fixture
from test_rsi_native_rejection import digest, rejection_evidence

from lunar_evolution import candidate_evaluation, candidate_execution_runner
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    persist_lineage_bytes_snapshot,
)
from lunar_evolution.producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
    persist_lineage_v2_descriptor,
)
from lunar_evolution.producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
from lunar_evolution.producer_bundle_transaction import (
    run_native_producer_bundle_publication_transaction,
)
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_native_rejection import NativeRSIRejectionFilePin
from lunar_evolution.rsi_producer_staging_capsule import retained_publication_evidence_bytes
from lunar_evolution.rsi_publication_lineage import (
    _PROTOCOL,
    _PROTOCOL_V2,
    RSIPublicationLineage,
    RSIPublicationLineageV2Inspection,
    StartedRSIRejectionInspection,
    _root_pin,
    _sha,
    _V2LineageEvidenceReader,
)


@pytest.fixture(autouse=True)
def inert_process_boundary(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("v2 history/capacity tests must not start processes or connect")

    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", _inert_fixture_process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_fixture_process)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


class Reader(_V2LineageEvidenceReader):
    """Test only the non-authoritative private projection reader, never an owner."""


def pin(name, *, raw=b"", size=None):
    return LineageSnapshotPin(name, _sha(raw), len(raw) if size is None else size, 1, 2, 1, 3,
                             mtime_ns=4, ctime_ns=5).to_dict()


def provenance_pin(*, size=41):
    return NativeRSIRejectionFilePin("native-rsi.rejection-provenance.json", digest("raw-p"), size,
                                     1, 2, 1, 3, mtime_ns=4, ctime_ns=5).to_dict()


def projection_history(tmp_path, outcomes):
    """Detached shape/capacity measurements only; these frames never authorize native work."""
    workspace = tmp_path / "workspace"
    (workspace / "evolution").mkdir(parents=True)
    reader = Reader()
    reader._workspace, reader._run_id = workspace, "run"
    reader._association = {"protocol": _PROTOCOL_V2, "run_id": "run", "workspace": _root_pin(workspace),
                           "run_request_sha256": digest("request"), "root_proof_sha256": digest("root"),
                           "policy_sha256": digest("policy"), "max_batches": 8}
    frames, batches = [], []
    archive, state_bytes = b"", b"{}"
    sources = {"archive": {"missing": True, "parent": _root_pin(workspace / "evolution")},
               "state": pin("state-before", raw=state_bytes)}

    def append_frame():
        terminals = [entry for entry in batches if entry["state"] == "terminal"]
        head = None if not terminals else {"journal_id": terminals[-1]["journal_id"],
            "terminal_sha256": terminals[-1]["terminal"]["terminal_sha256"],
            "lineage_sha256": terminals[-1]["terminal"]["descriptor_sha256"]}
        frames.append({"mode": "drs", "producer_known_rejection": True, "producer_multi_episode_publication": True,
                       "producer_publication_lineage": {**copy.deepcopy(reader._association), "batches": copy.deepcopy(batches),
                                                       "head": head, "rejections": reader._rejection_index(batches)}})

    for ordinal, outcome in enumerate(outcomes):
        before = ProducerLineageBeforeIntentV2(
            run_id="run", journal_id=f"j{ordinal}", ordinal=ordinal,
            archive=LineageSnapshotPin.from_dict(pin("archive-before.snapshot", raw=archive)),
            state=LineageSnapshotPin.from_dict(pin("state-before.snapshot", raw=state_bytes)),
            **reader._previous_v2(batches[-1] if batches else None),
        )
        entry = {"journal_id": before.journal_id, "ordinal": ordinal, "episode_id": f"e{ordinal}",
                 "request_sha256": digest(f"request-{ordinal}"), "memory_snapshot_sha256": digest("memory"),
                 "native_plan_sha256": digest(f"plan-{ordinal}"), "admission_plan": {}, "prepared_journal": {},
                 "before": before.to_dict(), "before_file_pin": pin("before-v2.json", size=19),
                 "snapshots": {"archive-before": before.archive.to_dict(), "state-before": before.state.to_dict()},
                 "before_sources": copy.deepcopy(sources), "state": "before", "evidence_pins": {}}
        batches.append(entry)
        append_frame()
        entry["evidence_pins"] = {"journal.prepared.json": pin("journal.prepared.json", size=23)}
        append_frame()
        if outcome == "R":
            rejected = ProducerLineageRejectedTerminalV2(
                run_id="run", journal_id=before.journal_id, episode_id=entry["episode_id"], ordinal=ordinal,
                before_sha256=before.digest(), prepared_journal_sha256=digest("prepared"),
                terminal_journal_sha256=digest(f"native-{ordinal}"), rejection_manifest_sha256=digest("manifest"),
                terminal_marker_sha256=digest("marker"), candidate_ids=(f"c{ordinal}",),
                archive_sha256=before.archive.sha256, state_sha256=before.state.sha256,
            )
            entry.update(state="rejected", rejected=rejected.to_dict(), rejected_file_pin=pin("rejected.json", size=29),
                         rejected_journal={}, rejection_provenance=None)
            for name in ("journal.json", "rejections.json", f"rejections/c{ordinal}.json"):
                entry["evidence_pins"][name] = pin("rejection-" + _sha(name.encode()) if name.startswith("rejections/") else name, size=31)
            append_frame()
            entry["rejection_provenance"] = {"provenance_sha256": digest("provenance"), "file_pin": provenance_pin()}
            append_frame()
        else:
            archive, state_bytes = f"published {ordinal}\n".encode(), f'{{"published":{ordinal}}}'.encode()
            staged = ProducerLineageStagedTransition("run", before.journal_id, ordinal, before.digest(), digest("staged"),
                digest("manifest"), _sha(archive), _sha(state_bytes), (f"c{ordinal}",))
            entry.update(state="staged", staged=staged.to_dict(), staged_file_pin=pin("staged.json"),
                         state_projection_sha256=_sha(state_bytes),
                         after_sources={"archive": pin("archive-after", raw=archive), "state": pin("state-after", raw=state_bytes)})
            entry["snapshots"].update({"archive-after": pin("archive-after.snapshot", raw=archive),
                                       "state-after": pin("state-after.snapshot", raw=state_bytes)})
            entry["evidence_pins"].update({name: pin(name) for name in ("journal.staged.json", "manifest.json", "preflight.json")})
            append_frame()
            terminal = ProducerLineageTerminal("run", before.journal_id, ordinal, staged.digest(), digest(f"marker-{ordinal}"),
                                              _sha(archive), _sha(state_bytes))
            sources = {"archive": pin("archive-before", raw=archive), "state": pin("state-before", raw=state_bytes)}
            entry.update(state="terminal", terminal=terminal.to_dict(), terminal_file_pin=pin("terminal.json"),
                         published_journal={}, head_sources=copy.deepcopy(sources))
            entry["evidence_pins"].update({name: pin(name) for name in ("journal.published.json", "terminal.json")})
            append_frame()
    reader._ledger = SimpleNamespace(controller_checkpoint_history=lambda _run: [(digest(f"frame-{i}"), state)
                                                                                 for i, state in enumerate(frames)])
    return reader, frames


@pytest.mark.parametrize("outcomes", ["RRR", "RPP", "PRP", "PPR", "PPP"])
def test_detached_history_preserves_attempt_order_published_head_and_rejection_index(tmp_path, outcomes):
    reader, frames = projection_history(tmp_path, outcomes)
    reader._validate_history_v2(frames[-1])
    wire = frames[-1]["producer_publication_lineage"]
    assert len(wire["batches"]) == 3
    assert [item["ordinal"] for item in wire["rejections"]] == [i for i, letter in enumerate(outcomes) if letter == "R"]
    expected = max((i for i, letter in enumerate(outcomes) if letter == "P"), default=None)
    assert (None if wire["head"] is None else wire["head"]["journal_id"]) == (None if expected is None else f"j{expected}")
    for ordinal, entry in enumerate(wire["batches"]):
        assert entry["before"]["previous_attempt_journal_id"] == (f"j{ordinal - 1}" if ordinal else None)
        if "P" not in outcomes[:ordinal]:
            assert entry["before"]["published_predecessor_journal_id"] is None
            assert entry["before_sources"]["archive"]["missing"] is True


@pytest.mark.parametrize("mutation", ["drop-before", "head", "index", "swap-pin", "remove-prepared", "downgrade", "replace-c2", "append-without-c2"])
def test_historical_rejection_mutation_cannot_be_hidden_by_correct_final_head(tmp_path, mutation):
    reader, frames = projection_history(tmp_path, "RR")
    target = frames[3]["producer_publication_lineage"]
    entry = target["batches"][0]
    if mutation == "drop-before":
        entry.pop("before")
    elif mutation == "head":
        target["head"] = {"journal_id": "j0", "terminal_sha256": digest("false"), "lineage_sha256": digest("false")}
    elif mutation == "index":
        target["rejections"] = []
    elif mutation == "swap-pin":
        entry["evidence_pins"]["journal.prepared.json"]["inode"] += 1
    elif mutation == "remove-prepared":
        frames.pop(1)
    elif mutation == "downgrade":
        frames.insert(4, copy.deepcopy(frames[1]))
    elif mutation == "replace-c2":
        entry["rejection_provenance"]["file_pin"]["inode"] += 1
    else:
        frames[3]["producer_publication_lineage"]["batches"][0]["rejection_provenance"] = None
    with pytest.raises((RSILearningError, ValueError, KeyError)):
        reader._validate_history_v2(frames[-1])


def test_c1_binding_is_unique_original_history_even_after_later_budget_frame(tmp_path):
    reader, frames = projection_history(tmp_path, "R")
    entry = frames[-1]["producer_publication_lineage"]["batches"][0]
    original = reader._binding_for_rejected_entry(entry)
    assert original.checkpoint_sha256 == digest("frame-2")
    frames.append({**copy.deepcopy(frames[-1]), "budget_reservation": "later permitted observation"})
    reader._validate_history_v2(frames[-1])
    assert reader._binding_for_rejected_entry(entry) == original


def test_c1_and_orphan_provenance_cannot_create_a_historical_rejection_binding(tmp_path):
    reader, frames = projection_history(tmp_path, "R")
    entry = frames[-1]["producer_publication_lineage"]["batches"][0]
    frames.pop(2)
    with pytest.raises(RSILearningError, match="rejection_c1_history_invalid"):
        reader._binding_for_rejected_entry(entry)


def test_v2_budget_counts_descriptors_native_evidence_and_original_0400_pin(tmp_path):
    _reader, frames = projection_history(tmp_path, "R")
    state = frames[-1]
    entry = state["producer_publication_lineage"]["batches"][0]
    expected = sum(value["size"] for value in entry["snapshots"].values())
    expected += entry["before_file_pin"]["size"] + entry["rejected_file_pin"]["size"]
    expected += sum(value["size"] for value in entry["evidence_pins"].values()) + provenance_pin()["size"]
    assert retained_publication_evidence_bytes(state) == expected
    assert RSIPublicationLineage._retained_bytes(state["producer_publication_lineage"], state) == expected
    state["producer_publication_lineage"]["protocol"] = _PROTOCOL
    assert retained_publication_evidence_bytes(state) == sum(value["size"] for value in entry["snapshots"].values())


@pytest.mark.parametrize("mutation", ["mode", "callback", "overflow", "wrong-0400"])
def test_v2_budget_refuses_before_any_path_access(tmp_path, monkeypatch, mutation):
    _reader, frames = projection_history(tmp_path, "R")
    state = frames[-1]
    entry = state["producer_publication_lineage"]["batches"][0]
    if mutation == "mode":
        state["producer_known_rejection"] = False
    elif mutation == "callback":
        class CallbackPin(dict):
            def items(self):
                pytest.fail("callback invoked")
        entry["before_file_pin"] = CallbackPin(entry["before_file_pin"])
    elif mutation == "overflow":
        for value in entry["snapshots"].values():
            value["size"] = MAX_LINEAGE_SNAPSHOT_BYTES
        entry["evidence_pins"] = {f"file-{i}": pin(f"file-{i}", size=MAX_LINEAGE_SNAPSHOT_BYTES) for i in range(8)}
    else:
        entry["rejection_provenance"]["file_pin"]["mode"] = 0o600
    monkeypatch.setattr("pathlib.Path.lstat", lambda *_a, **_k: pytest.fail("pure accounting accessed disk"))
    with pytest.raises(ValueError):
        retained_publication_evidence_bytes(state)


@pytest.mark.parametrize("inspection", [RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection])
def test_new_inspection_types_have_no_owner_launch_or_ack_methods(inspection):
    observation = object.__new__(inspection)
    assert not hasattr(observation, "__dict__")
    for name in ("retain_before", "retain_staged", "retain_terminal", "validate_launch", "_ack", "acknowledge_rejection_provenance"):
        assert not hasattr(observation, name)
    with pytest.raises(AttributeError):
        observation.rejection_provenance_binding = lambda: None


def test_original_owner_refuses_subclass_before_any_rejection_dto_or_path_work():
    class ForeignOwner(RSIPublicationLineage):
        pass
    owner = object.__new__(ForeignOwner)
    for method, arguments in ((owner.rejection_provenance_binding, ()), (owner.rejection_provenance_file_pin, ()),
                              (owner.acknowledge_rejection_provenance, (object(), object()))):
        with pytest.raises(RSILearningError, match="owner_invalid"):
            method(*arguments)


def test_original_owner_ack_checks_nested_callbacks_before_any_owner_or_io(monkeypatch):
    evidence = rejection_evidence()
    object.__setattr__(evidence.claim, "to_dict", lambda: pytest.fail("caller callback invoked"))
    owner = object.__new__(RSIPublicationLineage)
    owner._association, owner._phase = {"protocol": _PROTOCOL_V2}, "rejected"
    held_pin = NativeRSIRejectionFilePin.from_dict(provenance_pin())
    monkeypatch.setattr("pathlib.Path.lstat", lambda *_a, **_k: pytest.fail("path before shape"))
    with pytest.raises(ValueError, match="shape_invalid"):
        owner.acknowledge_rejection_provenance(evidence, held_pin)


def native_rejected_entry(tmp_path):
    context, strategy, drafts, plan, journal_id = _fixture(tmp_path, (999, 998))
    result = run_native_producer_bundle_publication_transaction(context.workspace, strategy, drafts, plan, journal_id=journal_id)
    prepared, terminal = result.journal, result.terminal_journal
    batch = context.workspace / "evolution/producer-batches" / journal_id
    reader = Reader()
    reader._workspace, reader._run_id = context.workspace, prepared.run_id
    reader._association = {"protocol": _PROTOCOL_V2}
    before_pins, sources = {}, {}
    for name in ("archive", "state"):
        path = context.workspace / "evolution" / (name + (".jsonl" if name == "archive" else ".json"))
        raw = path.read_bytes()
        _path, snapshot = persist_lineage_bytes_snapshot(context.workspace, journal_id, name=name + "-before",
            raw=raw, expected_sha256=_sha(raw))
        before_pins[name + "-before"] = snapshot.to_dict()
        sources[name] = capture_lineage_snapshot_pin(path, name=name + "-before").to_dict()
    before = ProducerLineageBeforeIntentV2(run_id=prepared.run_id, journal_id=journal_id, ordinal=0,
        archive=LineageSnapshotPin.from_dict(before_pins["archive-before"]), state=LineageSnapshotPin.from_dict(before_pins["state-before"]),
        **reader._previous_v2(None))
    _path, before_file = persist_lineage_v2_descriptor(context.workspace, before)
    native = _verify_terminal_batch_rejection_evidence(context.workspace, batch, prepared, terminal=terminal)
    rejected = ProducerLineageRejectedTerminalV2(run_id=prepared.run_id, journal_id=journal_id, episode_id=prepared.task_id, ordinal=0,
        before_sha256=before.digest(), prepared_journal_sha256=prepared.digest(), terminal_journal_sha256=terminal.digest(),
        rejection_manifest_sha256=native.manifest_sha256, terminal_marker_sha256=terminal.terminal_marker_sha256,
        candidate_ids=native.candidate_ids, archive_sha256=before.archive.sha256, state_sha256=before.state.sha256)
    _path, rejected_file = persist_lineage_v2_descriptor(context.workspace, rejected)
    evidence = {name: capture_lineage_snapshot_pin(batch / name,
        name="rejection-" + _sha(name.encode()) if name.startswith("rejections/") else name).to_dict()
        for name in ("journal.prepared.json", "journal.json", "rejections.json", *("rejections/" + item + ".json" for item in native.candidate_ids))}
    entry = {"journal_id": journal_id, "ordinal": 0, "episode_id": prepared.task_id,
        "request_sha256": digest("request"), "memory_snapshot_sha256": digest("memory"), "native_plan_sha256": digest("plan"),
        "admission_plan": plan.to_dict(), "prepared_journal": prepared.to_dict(), "before": before.to_dict(),
        "before_file_pin": before_file.to_dict(), "snapshots": before_pins, "before_sources": sources,
        "state": "rejected", "evidence_pins": evidence, "rejected": rejected.to_dict(),
        "rejected_file_pin": rejected_file.to_dict(), "rejected_journal": terminal.to_dict(), "rejection_provenance": None}
    return reader, entry, batch


def test_pinned_native_rejected_history_uses_original_receipts_after_later_live_publication(tmp_path):
    reader, entry, _batch = native_rejected_entry(tmp_path)
    original = reader._verify_rejected_entry(entry, ordinal=0, previous=None)
    (reader._workspace / "evolution/archive.jsonl").write_bytes(b"later archive\n")
    (reader._workspace / "evolution/state.json").write_bytes(b"later state\n")
    assert reader._verify_rejected_entry(entry, ordinal=0, previous=None) == original


@pytest.mark.parametrize("name", ["rejections.json", "journal.json", "rejected-descriptor", "candidate-evidence"])
def test_original_rejected_history_refuses_same_bytes_new_inode(tmp_path, name):
    reader, entry, batch = native_rejected_entry(tmp_path)
    path = (batch / "lineage/rejected.json" if name == "rejected-descriptor" else
            batch / ("rejections/" + entry["rejected"]["candidate_ids"][0] + ".json") if name == "candidate-evidence" else batch / name)
    replacement = path.with_name(path.name + ".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)
    with pytest.raises(ValueError):
        reader._verify_rejected_entry(entry, ordinal=0, previous=None)


def test_budget_ceiling_remains_64_mib():
    assert MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES == 64 * 1024 * 1024


def test_32_candidate_rejection_projection_measures_every_c2_pin_before_io(monkeypatch):
    class DetachedProjection:
        """Serialization only: this is never an original owner or checkpoint."""

        _projected_entry = RSIPublicationLineage._projected_entry
        _projected_rejected_entry = RSIPublicationLineage._projected_rejected_entry
        _capacity_check = RSIPublicationLineage._capacity_check

        @staticmethod
        def _is_v2():
            return True

        def _build_before_descriptor(self, journal_id, ordinal, head, archive, state):
            assert ordinal == 0 and head is None
            return ProducerLineageBeforeIntentV2(run_id=self._run_id, journal_id=journal_id,
                ordinal=ordinal, archive=archive, state=state, **Reader._previous_v2(None))

    observation = DetachedProjection()
    evidence = rejection_evidence()
    observation._plan, observation._request = evidence.plan, evidence.plan.request
    observation._run_id, observation._memory = evidence.plan.run_id, EMPTY_MEMORY_SNAPSHOT
    observation._admission_plan = SimpleNamespace(to_dict=dict)
    journal = _journal(*(replace(_candidate(index), candidate_id=f"c-{index}-" + "x" * 120,
                                preparation_receipt_sha256=digest(f"preparation-{index}"))
                         for index in range(32)), run_id=observation._run_id)
    monkeypatch.setattr("pathlib.Path.lstat", lambda *_a, **_k: pytest.fail("projection accessed disk"))
    entry = observation._projected_rejected_entry(journal, 0, None)
    assert len(entry["rejected"]["candidate_ids"]) == 32
    assert len(entry["evidence_pins"]) == 35
    assert entry["rejection_provenance"]["file_pin"]["mode"] == 0o400
    assert all(len(value["name"]) <= 128 for value in entry["evidence_pins"].values())
    wire = {"batches": [entry]}
    observation._payload = b"{}"
    observation._capacity_check(wire)
    observation._payload = b'{"retained":"' + b"x" * (112 * 1024 - 32) + b'"}'
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        observation._capacity_check(wire)
