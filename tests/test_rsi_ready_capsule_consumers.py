"""Capsule consumers preserve mode, original association and immutable references."""

from __future__ import annotations

import copy
import subprocess
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from test_rsi_native_gateway import digest, make_request
from test_rsi_publication_lineage_inspection import _ordered_history

import lunar_evolution.rsi_producer_staging_capsule as capsule
import lunar_evolution.rsi_python_episode_inputs as episode_inputs
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
)
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT, RSILearningError
from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage, _LineageEvidenceReader
from lunar_evolution.rsi_store import RSILedger


class _Stop(BaseException):
    """Stop after the reader seam, before unrelated binding parsing or IO."""


@pytest.fixture(autouse=True)
def _forbid_process(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess forbidden"))


def _reference(workspace, *, size=1):
    return {
        "protocol": capsule.READY_CAPSULE_PROTOCOL, "workspace": str(workspace), "journal_id": "journal-1",
        "workspace_identity": {"device": 1, "inode": 2},
        "file_pin": LineageSnapshotPin("rsi-ready.snapshot", "a" * 64, size, 1, 2, 1, 3,
                                       mtime_ns=4, ctime_ns=5).to_dict(),
    }


def _consumer_state(ready, *, flag=True):
    return {
        "run_id": "run-1", "mode": "drs", "producer_multi_episode_publication": flag,
        "producer_child_execution": True,
        "producer_episode_staging": {"episode-1": {
            "state": "ready", "identity": {"journal_id": "journal-1"}, "ready": ready,
        }},
    }


def _maximum_snapshot_wire():
    return {"batches": [{"snapshots": {
        name: LineageSnapshotPin(name + ".snapshot", "a" * 64, MAX_LINEAGE_SNAPSHOT_BYTES,
                                 1, 2, 1, 3, mtime_ns=4, ctime_ns=5).to_dict()
        for name in ("archive-before", "state-before", "archive-after", "state-after")
    }}]}


@pytest.mark.parametrize("capsule_ready", [False, True])
def test_store_materializes_before_child_proof_parse_and_preserves_raw_state(tmp_path, monkeypatch, capsule_ready):
    full = {name: {} for name in ("binding", "producer_checkpoint", "plan", "inputs", "input_manifest")}
    reference = _reference(tmp_path) if capsule_ready else full
    state = _consumer_state(reference, flag=capsule_ready)
    before = copy.deepcopy(state)
    calls = []

    def materialize(value, **arguments):
        calls.append((value, arguments))
        return full

    def parse(value, *, code):
        assert value is full["producer_checkpoint"]
        raise _Stop()

    monkeypatch.setattr(capsule, "materialize_ready", materialize)
    ledger = object.__new__(RSILedger)
    monkeypatch.setattr(ledger, "_checkpoint_binding", parse)
    with pytest.raises(_Stop):
        ledger._select_python_producer_checkpoint_tx(state, run_id="run-1", episode_id="episode-1", root=None)
    assert calls == [(reference, {"allow_capsule": capsule_ready, "expected_journal_id": "journal-1"})]
    assert state == before and state["producer_episode_staging"]["episode-1"]["ready"] is reference


@pytest.mark.parametrize("field", ["ready", "identity"])
def test_store_rejects_nested_callbacks_before_materialization(tmp_path, monkeypatch, field):
    observed = []

    class CallbackDict(dict):
        def items(self):
            observed.append("items")
            return super().items()

    state = _consumer_state(_reference(tmp_path))
    state["producer_episode_staging"]["episode-1"][field]["callback"] = CallbackDict()
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("materialize before shape gate"))
    with pytest.raises(ValueError, match="shape_invalid"):
        object.__new__(RSILedger)._select_python_producer_checkpoint_tx(
            state, run_id="run-1", episode_id="episode-1", root=None,
        )
    assert observed == []


@pytest.mark.parametrize("field,value", [("mode", "brs"), ("producer_child_execution", False),
                                         ("producer_child_execution", 1)])
def test_store_capsule_requires_drs_original_child_execution_before_reader(tmp_path, monkeypatch, field, value):
    state = _consumer_state(_reference(tmp_path))
    state[field] = value
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("forbidden mode read"))
    with pytest.raises(RSILearningError, match="child_proof_history_drift"):
        object.__new__(RSILedger)._select_python_producer_checkpoint_tx(
            state, run_id="run-1", episode_id="episode-1", root=None,
        )


def test_store_combined_budget_rejects_before_any_capsule_read(tmp_path, monkeypatch):
    state = _consumer_state(_reference(tmp_path))
    state["producer_publication_lineage"] = _maximum_snapshot_wire()
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("aggregate before read"))
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        object.__new__(RSILedger)._select_python_producer_checkpoint_tx(
            state, run_id="run-1", episode_id="episode-1", root=None,
        )


def _input_seam(tmp_path, monkeypatch):
    request = make_request()
    identity = {"journal_id": "journal-1", "intent": {"request": request.to_dict()},
                "memory": EMPTY_MEMORY_SNAPSHOT.to_dict()}
    reference = _reference(tmp_path)
    state = _consumer_state(reference)
    state["producer_episode_staging"] = {request.episode_id: {"state": "ready", "identity": identity, "ready": reference}}
    native = SimpleNamespace(workspace=tmp_path)
    root = SimpleNamespace(to_json=lambda: b"root")
    context = SimpleNamespace(original_producer_checkpoint=root)
    sidecar = SimpleNamespace(binding=SimpleNamespace(run_id="run-1"))
    ledger = object.__new__(RSILedger)
    monkeypatch.setattr(episode_inputs, "_context", lambda _: (native, sidecar))
    monkeypatch.setattr(ledger, "read_only_observations", nullcontext)
    monkeypatch.setattr(ledger, "resolve_python_producer_checkpoint", lambda *a, **k: (root, object()))
    monkeypatch.setattr(ledger, "controller_checkpoint", lambda _: ("a" * 64, state))
    return request, reference, state, context, ledger


def test_episode_inputs_binds_original_workspace_and_identity_journal_before_binding_parse(tmp_path, monkeypatch):
    request, reference, state, context, ledger = _input_seam(tmp_path, monkeypatch)
    before = copy.deepcopy(state)
    calls = []

    def materialize(value, **arguments):
        calls.append((value, arguments))
        return {"binding": {}}

    def stop_parse(_):
        raise _Stop()

    monkeypatch.setattr(episode_inputs, "materialize_ready", materialize)
    monkeypatch.setattr(episode_inputs, "parse_python_producer_binding", stop_parse)
    with pytest.raises(_Stop):
        episode_inputs.resolve_python_rsi_episode_input_context(
            context, ledger, request, EMPTY_MEMORY_SNAPSHOT, expected_checkpoint_sha256="a" * 64,
        )
    assert calls == [(reference, {"allow_capsule": True, "expected_workspace": tmp_path,
                                  "expected_journal_id": "journal-1"})]
    assert state == before


def test_episode_inputs_rejects_request_drift_before_capsule_read(tmp_path, monkeypatch):
    request, _reference_value, state, context, ledger = _input_seam(tmp_path, monkeypatch)
    state["producer_episode_staging"][request.episode_id]["identity"]["intent"]["request"]["episode_id"] = "foreign"
    monkeypatch.setattr(episode_inputs, "materialize_ready", lambda *a, **k: pytest.fail("drift capsule read"))
    with pytest.raises(RSILearningError, match="request_memory_drift"):
        episode_inputs.resolve_python_rsi_episode_input_context(
            context, ledger, request, EMPTY_MEMORY_SNAPSHOT, expected_checkpoint_sha256="a" * 64,
        )


def test_episode_inputs_combined_budget_rejects_before_capsule_read(tmp_path, monkeypatch):
    request, _reference_value, state, context, ledger = _input_seam(tmp_path, monkeypatch)
    state["producer_publication_lineage"] = _maximum_snapshot_wire()
    monkeypatch.setattr(episode_inputs, "materialize_ready", lambda *a, **k: pytest.fail("aggregate before inputs read"))
    with pytest.raises(RSILearningError, match="episode_evidence_invalid") as error:
        episode_inputs.resolve_python_rsi_episode_input_context(
            context, ledger, request, EMPTY_MEMORY_SNAPSHOT, expected_checkpoint_sha256="a" * 64,
        )
    assert isinstance(error.value.__cause__, RSILearningError)
    assert "aggregate_exhausted" in str(error.value.__cause__)


def _staging_history(reference):
    request = make_request()
    memory = EMPTY_MEMORY_SNAPSHOT
    import hashlib

    from lunar_evolution.candidate_evaluation_spec import canonical_json

    token = hashlib.sha256(canonical_json({"run_id": "run-1", "episode_id": request.episode_id,
                                         "request": request.digest()})).hexdigest()[:32]
    policy = {"fixture": "pure-capsule-history"}
    intent = {"request": request.to_dict()}
    identity = {
        "run_id": "run-1", "episode_id": request.episode_id, "original_run_request_sha256": digest("run-request"),
        "original_run_record_sha256": digest("run-record"), "origin_checkpoint_sha256": "head-0", "intent": intent,
        "request_sha256": request.digest(), "memory": memory.to_dict(), "memory_snapshot_sha256": memory.digest(),
        "journal_id": "rsi-stage-" + token, "launch_id": "rsi-launch-" + token, "policy": policy,
    }
    initial = {"run_id": "run-1", "mode": "drs", "producer_child_execution": True,
               "producer_multi_episode_publication": True, "producer_staging_policy": policy,
               "producer_episode_staging": {}, "intents": {request.episode_id: intent}}
    preparing = copy.deepcopy(initial)
    preparing["producer_episode_staging"][request.episode_id] = {
        "state": "preparing", "identity": identity, "ready": None, "failure_code": None,
    }
    reference = copy.deepcopy(reference)
    reference["journal_id"] = identity["journal_id"]
    ready = copy.deepcopy(preparing)
    ready["producer_episode_staging"][request.episode_id].update(state="ready", ready=reference)
    return request.episode_id, [("head-0", initial), ("head-1", preparing), ("head-2", ready),
                                ("head-3", copy.deepcopy(ready))]


def test_staging_history_compares_original_reference_without_materialization(tmp_path, monkeypatch):
    _episode, history = _staging_history(_reference(tmp_path))
    before = copy.deepcopy(history)
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("history hydration"))
    object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")
    assert history == before


@pytest.mark.parametrize("mutation", ["pin", "retrofit", "mode", "child_execution", "flag", "flag_int"])
def test_staging_history_refuses_reference_rewrite_and_mode_drift(tmp_path, mutation):
    episode, history = _staging_history(_reference(tmp_path))
    if mutation == "pin":
        history[-1][1]["producer_episode_staging"][episode]["ready"]["file_pin"]["inode"] += 1
    elif mutation == "retrofit":
        history[-2][1]["producer_episode_staging"][episode]["ready"] = {
            field: {} for field in ("binding", "producer_checkpoint", "plan", "inputs", "input_manifest")
        }
    else:
        field, value = {"mode": ("mode", "brs"), "child_execution": ("producer_child_execution", False),
                        "flag": ("producer_multi_episode_publication", False),
                        "flag_int": ("producer_multi_episode_publication", 1)}[mutation]
        history[-1][1][field] = value
    with pytest.raises(RSILearningError, match="child_proof_history_drift"):
        object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")


def test_staging_history_combined_budget_refuses_earlier_frame_even_if_current_is_small(tmp_path, monkeypatch):
    _episode, history = _staging_history(_reference(tmp_path))
    history[-2][1]["producer_publication_lineage"] = _maximum_snapshot_wire()
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("historical bound before read"))
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")


def test_owner_retained_bytes_includes_capsule_and_snapshot_in_same_limit(tmp_path):
    state = _consumer_state(_reference(tmp_path, size=11))
    wire = {"batches": [{"snapshots": {"archive-before": {"size": 17}}}]}
    assert RSIPublicationLineage._retained_bytes(wire, state) == 28
    wire["batches"][0]["snapshots"]["archive-before"]["size"] = MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - 10
    with pytest.raises(RSILearningError, match="capacity_exceeded"):
        RSIPublicationLineage._retained_bytes(wire, state)


def test_historical_frame_counts_ready_capsule_before_any_materialization(tmp_path, monkeypatch):
    frames = _ordered_history()
    for frame in frames:
        for field in ("snapshots", "before_sources", "after_sources", "head_sources"):
            for pin in frame["batches"][0].get(field, {}).values():
                pin["size"] = MAX_LINEAGE_SNAPSHOT_BYTES

    class Ledger:
        def controller_checkpoint_history(self, _):
            return [(str(index), {**_consumer_state(_reference(tmp_path)),
                                  "producer_publication_lineage": frame}) for index, frame in enumerate(frames)]

    class Reader(_LineageEvidenceReader):
        __slots__ = ("_association", "_ledger", "_run_id")

    reader = Reader()
    reader._ledger, reader._association, reader._run_id = Ledger(), {}, "run-1"
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("capacity before capsule IO"))
    with pytest.raises(RSILearningError, match="capacity_exceeded|aggregate_exhausted"):
        reader._validate_history({**_consumer_state(_reference(tmp_path)),
                                  "producer_publication_lineage": frames[-1]})


def test_lineage_history_checks_past_frame_budget_before_reading_current_small_capsule(tmp_path, monkeypatch):
    current = _consumer_state(_reference(tmp_path))
    past = {**copy.deepcopy(current), "producer_publication_lineage": _maximum_snapshot_wire()}

    class Ledger:
        def controller_checkpoint_history(self, _):
            return [("past", past), ("current", current)]

    class Reader(_LineageEvidenceReader):
        __slots__ = ("_association", "_ledger", "_run_id")

    reader = Reader()
    reader._association, reader._ledger, reader._run_id = {}, Ledger(), "run-1"
    monkeypatch.setattr(capsule, "materialize_ready", lambda *a, **k: pytest.fail("past-frame budget before read"))
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        reader._validate_history(current)
