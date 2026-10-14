"""Read-only publication proof rejects changed held evidence; workers stay inert."""
from __future__ import annotations

import copy
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_bundle_recovery import _journal, _plan
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _successful_fixture
from test_rsi_native_gateway import bundle, digest, make_request, plan_factory
from test_rsi_producer_staging_controller import _run

from lunar_evolution import RSILearningController, RSILearningError
from lunar_evolution.producer_bundle_admission import parse_producer_bundle_admission_plan
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
    ProducerLineageTerminal,
)
from lunar_evolution.producer_bundle_publication import parse_producer_bundle_publication_journal
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot
from lunar_evolution.rsi_native_candidate import (
    map_native_receipts_to_solver_result,
    select_native_candidate,
)
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready
from lunar_evolution.rsi_publication_lineage import (
    RSIPublicationLineageInspection,
    _LineageEvidenceReader,
    _require_marker_absent,
)


@pytest.fixture(autouse=True)
def _forbid_process(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess forbidden"))


def _published(tmp_path, monkeypatch):
    value, old, supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=old.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
    )
    observation.controller = controller
    result = _run(controller, value)
    assert result.status == "completed" and len(observation.attempts) == 1
    _head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    entry = state["producer_publication_lineage"]["batches"][0]
    request = SolverRequest.from_dict(state["intents"][entry["episode_id"]]["request"])
    memory = MemorySnapshot.from_dict(state["root_snapshot"])
    ready = materialize_ready(
        state["producer_episode_staging"][entry["episode_id"]]["ready"],
        allow_capsule=state["producer_multi_episode_publication"] is True,
        expected_workspace=value.root, expected_journal_id=entry["journal_id"],
    )
    native_plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
    inspection = RSIPublicationLineageInspection(controller, request=request, memory=memory, native_plan=native_plan)
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    journal = parse_producer_bundle_publication_journal(entry["published_journal"])
    return value, controller, inspection, plan, journal, supplier, observation


def test_durable_inspection_is_readonly_and_does_not_recreate_execution_owner(tmp_path, monkeypatch):
    value, controller, inspection, plan, journal, supplier, observation = _published(tmp_path, monkeypatch)
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    assert controller._producer_publication_dispatch is None
    assert not hasattr(inspection, "__dict__")
    for name in ("retain_before", "retain_staged", "retain_terminal", "validate_launch", "_ack"):
        assert not hasattr(inspection, name)
    publication = inspection.inspect(value.root, plan, journal)
    assert publication.status == "published" and publication.journal_sha256 == journal.digest()
    assert publication.candidate_ids == tuple(slot.candidate_id for slot in journal.candidates)
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert len(supplier.observations) == len(observation.attempts) == 1


def test_inspection_cannot_adopt_new_controller_checkpoint(tmp_path, monkeypatch):
    value, _controller, inspection, plan, journal, _supplier, _observation = _published(tmp_path, monkeypatch)
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    state["foreign_readonly_update"] = True
    value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=head)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="inspection_checkpoint_drift"):
        inspection.inspect(value.root, plan, journal)
    assert inspection._head == head
    assert _inventory(value.root) == before


def test_inspection_cannot_use_foreign_thread(tmp_path, monkeypatch):
    value, _controller, inspection, plan, journal, _supplier, _observation = _published(tmp_path, monkeypatch)
    before = _inventory(value.root)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(inspection.inspect, value.root, plan, journal)
        with pytest.raises(RSILearningError, match="inspection_owner_drift"):
            future.result()
    assert _inventory(value.root) == before


@pytest.mark.parametrize("target", ["archive-before", "state-after", "archive-head", "prepared"])
def test_inspection_rejects_same_byte_inode_replacement(tmp_path, monkeypatch, target):
    value, _controller, inspection, plan, journal, _supplier, _observation = _published(tmp_path, monkeypatch)
    batch = value.root / "evolution/producer-batches" / journal.journal_id
    path = {
        "archive-before": batch / "lineage/archive-before.snapshot",
        "state-after": batch / "lineage/state-after.snapshot",
        "archive-head": value.root / "evolution/archive.jsonl",
        "prepared": batch / "journal.prepared.json",
    }[target]
    original = path.lstat().st_ino
    replacement = Path(str(path) + ".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)
    assert path.lstat().st_ino != original
    before = _inventory(value.root)
    with pytest.raises(ValueError):
        inspection.inspect(value.root, plan, journal)
    assert _inventory(value.root) == before


def test_inspection_refuses_unknown_publication_marker_without_repair(tmp_path, monkeypatch):
    value, _controller, inspection, plan, journal, _supplier, _observation = _published(tmp_path, monkeypatch)
    marker = value.root / "evolution/producer-publication.json"
    marker.write_bytes(b'{"status":"unknown"}')
    marker.chmod(0o600)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="publication_marker_exists"):
        inspection.inspect(value.root, plan, journal)
    assert _inventory(value.root) == before


def test_inspection_method_cannot_be_shadowed_on_instance(tmp_path, monkeypatch):
    _value, _controller, inspection, _plan, _journal, _supplier, _observation = _published(tmp_path, monkeypatch)
    with pytest.raises(AttributeError):
        inspection.inspect = lambda *args: None


@pytest.mark.parametrize("target", ["bundle_collection", "candidate_collection", "candidate_child"])
def test_inspection_rejects_nested_callbacks_before_serialization(tmp_path, target):
    observed = []

    class CallbackTuple(tuple):
        def __iter__(self):
            observed.append("iter")
            return super().__iter__()

    class CallbackChild:
        def to_dict(self):
            observed.append("to_dict")
            return {}

    plan = _plan()
    journal = _journal(plan)
    if target == "bundle_collection":
        object.__setattr__(plan, "bundles", CallbackTuple(plan.bundles))
    elif target == "candidate_collection":
        object.__setattr__(journal, "candidates", CallbackTuple(journal.candidates))
    else:
        object.__setattr__(journal, "candidates", (CallbackChild(),))
    inspection = object.__new__(RSIPublicationLineageInspection)
    inspection._workspace = tmp_path
    with pytest.raises(ValueError, match="shape_invalid"):
        RSIPublicationLineageInspection.inspect(inspection, tmp_path, plan, journal)
    assert observed == []


def _phase_entry(phase):
    def pin(name):
        return LineageSnapshotPin(name, "a" * 64, 1, 1, 2, 1, 3, mtime_ns=4, ctime_ns=5).to_dict()

    entry = {
        "journal_id": "journal-1", "ordinal": 0, "episode_id": "run-1-target-0",
        "request_sha256": "a" * 64, "memory_snapshot_sha256": "a" * 64,
        "native_plan_sha256": "a" * 64, "admission_plan": {}, "prepared_journal": {},
        "before": {}, "before_file_pin": pin("before.json"), "state": phase,
        "before_sources": {name: pin(name + "-before") for name in ("archive", "state")},
        "snapshots": {name + "-before": pin(name + "-before.snapshot") for name in ("archive", "state")},
        "evidence_pins": {"journal.prepared.json": pin("journal.prepared.json")},
    }
    if phase in {"staged", "terminal"}:
        entry.update(staged={}, staged_file_pin=pin("staged.json"), state_projection_sha256="a" * 64,
                     after_sources={name: pin(name + "-after") for name in ("archive", "state")})
        entry["snapshots"].update({name + "-after": pin(name + "-after.snapshot") for name in ("archive", "state")})
        entry["evidence_pins"].update({name: pin(name) for name in ("journal.staged.json", "manifest.json", "preflight.json")})
    if phase == "terminal":
        entry.update(terminal={}, terminal_file_pin=pin("terminal.json"), published_journal={},
                     head_sources={name: pin(name + "-before") for name in ("archive", "state")})
        entry["evidence_pins"].update({name: pin(name) for name in ("journal.published.json", "terminal.json")})
    return entry


@pytest.mark.parametrize("phase", ["before", "staged", "terminal"])
def test_history_phase_shape_requires_all_original_pins(phase):
    entry = _phase_entry(phase)
    reader = _LineageEvidenceReader()
    reader._validate_entry_shape(entry)
    for field in ("before_file_pin", "before_sources", "snapshots", "evidence_pins"):
        changed = copy.deepcopy(entry)
        changed.pop(field)
        with pytest.raises(ValueError, match="history_phase_pins_invalid"):
            reader._validate_entry_shape(changed)
    if phase in {"staged", "terminal"}:
        for field in ("after_sources", "staged_file_pin"):
            changed = copy.deepcopy(entry)
            changed.pop(field)
            with pytest.raises(ValueError, match="history_phase_pins_invalid"):
                reader._validate_entry_shape(changed)


@pytest.mark.parametrize("field", ["before_sources", "after_sources", "head_sources"])
def test_empty_or_renamed_source_pin_map_cannot_skip_original_file_gate(field):
    reader = _LineageEvidenceReader()
    entry = _phase_entry("terminal")
    entry[field] = {}
    with pytest.raises(ValueError, match="source_pins_invalid"):
        reader._validate_entry_shape(entry)
    entry = _phase_entry("terminal")
    entry[field]["archive"]["name"] = "foreign-source"
    with pytest.raises(ValueError, match="source_pins_invalid"):
        reader._validate_entry_shape(entry)


@pytest.mark.parametrize("phase", ["before", "staged"])
def test_later_terminal_fields_cannot_appear_as_precommit_history(phase):
    entry = _phase_entry("terminal")
    entry["state"] = phase
    with pytest.raises(ValueError, match="history_phase_pins_invalid"):
        _LineageEvidenceReader()._validate_entry_shape(entry)


def _read_history(frames):
    class Ledger:
        def controller_checkpoint_history(self, run_id):
            assert run_id == "run-1"
            return [(str(index), {"producer_multi_episode_publication": True,
                                  "producer_publication_lineage": wire}) for index, wire in enumerate(frames)]

    class Reader(_LineageEvidenceReader):
        __slots__ = ("_association", "_ledger", "_run_id")

    reader = Reader()
    reader._association, reader._run_id, reader._ledger = {}, "run-1", Ledger()
    reader._validate_history({"producer_multi_episode_publication": True, "producer_publication_lineage": frames[-1]})


def _ordered_history():
    frames = []
    terminal = ProducerLineageTerminal("run-1", "journal-1", 0, "a" * 64, "b" * 64, "a" * 64, "a" * 64)
    for phase, acknowledged in (("before", False), ("before", True), ("staged", True), ("terminal", True)):
        entry = _phase_entry(phase)
        entry["before"] = {"run_id": "run-1", "journal_id": "journal-1"}
        if not acknowledged:
            entry["evidence_pins"] = {}
        if phase == "terminal":
            entry["terminal"] = terminal.to_dict()
        head = None if phase != "terminal" else {
            "journal_id": "journal-1", "terminal_sha256": terminal.terminal_sha256, "lineage_sha256": terminal.digest(),
        }
        frames.append({"batches": [entry], "head": head, "rejections": []})
    return frames


def test_original_phase_cas_history_is_valid():
    _read_history(_ordered_history())


def test_retained_history_rejects_aggregate_before_any_snapshot_io():
    frames = _ordered_history()
    second = _phase_entry("before")
    second.update(journal_id="journal-2", ordinal=1, before={"run_id": "run-1", "journal_id": "journal-2"}, evidence_pins={})
    frames.append({**copy.deepcopy(frames[-1]), "batches": [copy.deepcopy(frames[-1]["batches"][0]), second]})
    for frame in frames:
        for entry in frame["batches"]:
            for field in ("snapshots", "before_sources", "after_sources", "head_sources"):
                for pin in entry.get(field, {}).values():
                    pin["size"] = MAX_LINEAGE_SNAPSHOT_BYTES
    with pytest.raises(RSILearningError, match="capacity_exceeded|aggregate_exhausted"):
        _read_history(frames)


@pytest.mark.parametrize("kind", ["first_terminal", "append_terminal", "prepared_pin_first_at_stage"])
def test_terminal_readback_cannot_invent_original_before_and_prepared_cas(kind):
    frames = _ordered_history()
    if kind == "first_terminal":
        frames = [frames[-1]]
    elif kind == "append_terminal":
        entry = copy.deepcopy(frames[-1]["batches"][0])
        entry.update(journal_id="journal-2", ordinal=1, before={"run_id": "run-1", "journal_id": "journal-2"})
        frames.append({**copy.deepcopy(frames[-1]), "batches": [copy.deepcopy(frames[-1]["batches"][0]), entry]})
    else:
        frames.pop(1)
    with pytest.raises(RSILearningError, match="history_introduction_invalid|history_prepared_pin_missing"):
        _read_history(frames)


def test_dangling_publication_marker_is_not_absence(tmp_path):
    evolution = tmp_path / "evolution"
    evolution.mkdir()
    marker = evolution / "producer-publication.json"
    marker.symlink_to(evolution / "missing-target")
    before = _inventory(tmp_path)
    with pytest.raises(RSILearningError, match="publication_marker_exists"):
        _require_marker_absent(tmp_path)
    assert _inventory(tmp_path) == before


def _durable_native_fixture(tmp_path):
    request = make_request()
    plan = plan_factory(request, EMPTY_MEMORY_SNAPSHOT)
    receipts = bundle(request, plan)
    saved = {
        "plan": plan.to_dict(), "publication_journal_sha256": digest("journal"),
        "producer_execution_receipt_sha256": digest("producer"), "provenance_sha256": digest("provenance"),
        "bundle": {name: getattr(receipts, name).to_dict() for name in ("candidate", "execution", "evaluation", "publication")},
    }
    entry = {
        "journal_id": plan.journal_id,
        "published_journal": {
            "journal_sha256": saved["publication_journal_sha256"],
            "native_execution_receipt_sha256": saved["producer_execution_receipt_sha256"],
            "candidates": [{
                "candidate_id": receipts.candidate.candidate_id, "status": "admitted",
                "preparation_receipt_sha256": receipts.candidate.candidate_receipt_sha256,
                "execution_receipt_sha256": receipts.execution.receipt_sha256,
                "evaluation_receipt_sha256": receipts.evaluation.receipt_sha256,
                "publication_receipt_sha256": receipts.publication.receipt_sha256,
            }],
        },
    }
    result = map_native_receipts_to_solver_result(
        request, select_native_candidate(request, [receipts.candidate]),
        receipts.execution, receipts.evaluation, receipts.publication,
    )
    result = replace(result, solver_provenance=tuple(sorted({
        **dict(result.solver_provenance), "native_plan_sha256": plan.plan_sha256,
        "native_provenance_sha256": saved["provenance_sha256"],
    }.items())))

    class Reader(_LineageEvidenceReader):
        __slots__ = ("_workspace",)

    reader = Reader()
    reader._workspace = tmp_path
    return reader, request, plan, entry, saved, result


def test_durable_native_result_reconstructs_exact_receipts_with_two_readonly_observations(tmp_path, monkeypatch):
    reader, request, plan, entry, saved, result = _durable_native_fixture(tmp_path)
    before = _inventory(tmp_path)
    observations = []

    def observe(path):
        observations.append(path)
        return copy.deepcopy(saved)

    monkeypatch.setattr("lunar_evolution.rsi_native_provenance.read_native_rsi_provenance", observe)
    assert result.solver_score is None
    reader._verify_durable_native_result(entry, request, plan, result)
    assert observations == [tmp_path / "evolution/producer-batches" / plan.journal_id] * 2
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("drift", [
    "plan", "journal", "producer", "plan_provenance", "provenance", "preparation_receipt",
    "execution_receipt", "evaluation_receipt", "publication_receipt", "candidate_status",
    "candidate_duplicate", "invented_score", "readback",
])
def test_durable_native_result_rejects_foreign_evidence_without_recovery(tmp_path, monkeypatch, drift):
    reader, request, plan, entry, saved, result = _durable_native_fixture(tmp_path)
    before = _inventory(tmp_path)
    if drift == "plan":
        saved["plan"]["launch_id"] = "foreign-launch"
    elif drift in {"journal", "producer"}:
        field = {"journal": "publication_journal_sha256", "producer": "producer_execution_receipt_sha256"}[drift]
        saved[field] = digest("foreign")
    elif drift in {"plan_provenance", "provenance"}:
        field = "native_plan_sha256" if drift == "plan_provenance" else "native_provenance_sha256"
        result = replace(result, solver_provenance=tuple(sorted({**dict(result.solver_provenance), field: digest("foreign")}.items())))
    elif drift.endswith("_receipt"):
        entry["published_journal"]["candidates"][0][drift + "_sha256"] = digest("foreign")
    elif drift == "candidate_status":
        entry["published_journal"]["candidates"][0]["status"] = "rejected"
    elif drift == "candidate_duplicate":
        entry["published_journal"]["candidates"].append(copy.deepcopy(entry["published_journal"]["candidates"][0]))
    elif drift == "invented_score":
        result = replace(result, solver_score=9)
    reads = []

    def observe(path):
        reads.append(path)
        value = copy.deepcopy(saved)
        if drift == "readback" and len(reads) == 2:
            value["provenance_sha256"] = digest("changed-between-reads")
        return value

    monkeypatch.setattr("lunar_evolution.rsi_native_provenance.read_native_rsi_provenance", observe)
    with pytest.raises(RSILearningError, match="inspection_native_result_drift"):
        reader._verify_durable_native_result(entry, request, plan, result)
    assert len(reads) == (2 if drift == "readback" else 1)
    assert _inventory(tmp_path) == before
