"""Actual SQLite/file observer components; these fixtures grant no native authority."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import (
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    persist_lineage_bytes_snapshot,
    persist_lineage_descriptor,
)
from lunar_evolution.producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
    persist_lineage_v2_descriptor,
)
from lunar_evolution.rsi_brs_reserved_owner import (
    read_reserved_brs_completion_prefix,
    read_reserved_brs_prefix,
    reserved_before,
    reserved_prefix_identity,
    reserved_verify_before_links,
    reserved_verify_descriptor,
    reserved_wire_scope,
)
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from lunar_evolution.rsi_store import RSILedger


def _sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _fixture(tmp_path, outcomes):
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    run_id, memory = "observed", EMPTY_MEMORY_SNAPSHOT
    requests = tuple(SolverRequest.build(episode_id=f"{run_id}-practice-0-{ordinal}",
        contract_sha256=_sha("contract"), evaluator_sha256=_sha("evaluator"),
        environment_sha256=_sha("environment"), memory_snapshot_sha256=memory.digest(), solver_id="fixture")
        for ordinal in range(len(outcomes) + 1))
    state = {"run_id": run_id, "mode": "brs", "status": "running", "plan": {
        "mode": "brs", "wave": 0, "max_workers": 1, "reserved_native_serial": True,
        "practices": [{} for _ in requests]}, "pins": {}, "root_snapshot": memory.to_dict(),
        "memory_snapshot": memory.to_dict(), "budget_state": {},
        "intents": {request.episode_id: {"request": request.to_dict()} for request in requests}, "executions": {}}
    created = ledger.create_run(run_id, _sha("run"), state)
    ledger.transition(run_id, state="running", expected_record_sha256=created.record_sha256)
    with ledger.controller_lock(run_id):
        head = ledger.write_controller_checkpoint(run_id, state, expected_sha256=None)
    original = head, canonical_json(state)
    association = {"protocol": "lunar-rsi-brs-lineage-checkpoint-v1", "run_id": run_id,
        "workspace": {"path": str(tmp_path)}, "run_request_sha256": _sha("run"),
        "root_proof_sha256": _sha("root"), "policy_sha256": _sha("policy"), "max_batches": 8}
    wire = {**association, "batches": [], "head": None, "rejections": []}
    previous = published = None
    archive, population = b"archive-0", b"state-0"
    for ordinal, outcome in enumerate(outcomes):
        request, journal_id = requests[ordinal], f"journal-{ordinal}"
        batch = tmp_path / "evolution/producer-batches" / journal_id
        batch.mkdir(parents=True)
        snapshots = {}
        for name, raw in (("archive-before", archive), ("state-before", population)):
            _path, pin = persist_lineage_bytes_snapshot(tmp_path, journal_id, name=name,
                raw=raw, expected_sha256=hashlib.sha256(raw).hexdigest())
            snapshots[name] = pin.to_dict()
        from lunar_evolution.producer_bundle_lineage import LineageSnapshotPin
        pins = [LineageSnapshotPin.from_dict(snapshots[name]) for name in ("archive-before", "state-before")]
        before = (ProducerLineageBeforeIntent(run_id, journal_id, ordinal, None, None, *pins) if ordinal == 0 else
            ProducerLineageBeforeIntentV2(run_id, journal_id, ordinal, *previous,
                *(published or (None, None, None)), *pins))
        _path, before_pin = (persist_lineage_descriptor(tmp_path, before) if ordinal == 0 else
                             persist_lineage_v2_descriptor(tmp_path, before))
        plan = _sha(f"plan-{ordinal}")
        entry = {"journal_id": journal_id, "ordinal": ordinal, "episode_id": request.episode_id,
            "request_sha256": request.digest(), "memory_snapshot_sha256": memory.digest(), "native_plan_sha256": plan,
            "before": before.to_dict(), "before_file_pin": before_pin.to_dict(), "snapshots": snapshots,
            "evidence_pins": {}, "state": "terminal" if outcome == "published" else "rejected"}
        if outcome == "published":
            archive, population = f"archive-{ordinal + 1}".encode(), f"state-{ordinal + 1}".encode()
            for name, raw in (("archive-after", archive), ("state-after", population)):
                _path, pin = persist_lineage_bytes_snapshot(tmp_path, journal_id, name=name,
                    raw=raw, expected_sha256=hashlib.sha256(raw).hexdigest())
                snapshots[name] = pin.to_dict()
            staged = ProducerLineageStagedTransition(run_id, journal_id, ordinal, before.digest(), _sha("staged"),
                _sha("manifest"), hashlib.sha256(archive).hexdigest(), hashlib.sha256(population).hexdigest(),
                (f"candidate-{ordinal}",))
            _path, staged_pin = persist_lineage_descriptor(tmp_path, staged)
            terminal = ProducerLineageTerminal(run_id, journal_id, ordinal, staged.digest(), _sha("marker"),
                staged.archive_after_sha256, staged.state_after_sha256)
            _path, terminal_pin = persist_lineage_descriptor(tmp_path, terminal)
            entry.update(staged=staged.to_dict(), staged_file_pin=staged_pin.to_dict(),
                         terminal=terminal.to_dict(), terminal_file_pin=terminal_pin.to_dict())
            previous = (journal_id, outcome, terminal.terminal_sha256, terminal.digest())
            published = journal_id, terminal.terminal_sha256, terminal.digest()
            wire["head"] = dict(zip(("journal_id", "terminal_sha256", "lineage_sha256"), published))
        else:
            terminal = ProducerLineageRejectedTerminalV2(run_id, journal_id, request.episode_id, ordinal,
                before.digest(), _sha("prepared"), _sha("rejected"), _sha("manifest"), _sha("marker"),
                (f"candidate-{ordinal}",), pins[0].sha256, pins[1].sha256)
            _path, terminal_pin = persist_lineage_v2_descriptor(tmp_path, terminal)
            entry.update(rejected=terminal.to_dict(), rejected_file_pin=terminal_pin.to_dict())
            previous = journal_id, outcome, terminal.terminal_marker_sha256, terminal.digest()
            wire["rejections"].append({"ordinal": ordinal, "journal_id": journal_id, "rejected_sha256": terminal.digest()})
        status = "completed" if outcome == "published" else "failed"
        receipt = (_sha("candidate"), _sha("execution"), _sha("evaluation")) if outcome == "published" else (None, None, None)
        result = SolverResult(request.episode_id, request.digest(), status, *receipt, _sha("trace"))
        verifier = VerifierDecision(request.episode_id, "fail", _sha("verifier"), "fixture", _sha("v-source"),
                                   (VerifierCheck("diagnosis", "fail", _sha("check")),))
        episode = PracticeEpisode(request.episode_id, run_id, request.contract_sha256, request.evaluator_sha256,
            request.environment_sha256, memory.digest(), request.solver_id, status,
            verifier if outcome == "published" else None, wave=0, ordinal=ordinal, request_sha256=request.digest(),
            trace_digest=result.trace_digest, candidate_receipt_sha256=receipt[0], execution_receipt_sha256=receipt[1],
            official_evaluation_receipt_sha256=receipt[2], terminal_reason="inert-failed" if status == "failed" else None)
        ledger.create_episode_record(episode)
        claim = ledger.claim_native_episode(request, plan_sha256=plan)
        ledger.publish_native_episode_result(request, plan_sha256=plan, result=result, expected_claim=claim)
        execution = {"episode": episode.to_record_dict(), "request": request.to_dict(),
                     "result": result.to_dict(), "verifier": verifier.to_dict()}
        wire["batches"].append(entry)
        state = {**deepcopy(state), "phase": "evaluated", "current_episode_id": request.episode_id,
            "executions": {**state["executions"], request.episode_id: execution},
            "producer_publication_lineage": deepcopy(wire)}
        with ledger.controller_lock(run_id):
            head = ledger.write_controller_checkpoint(run_id, state, expected_sha256=head)
    return SimpleNamespace(ledger=ledger, requests=requests, state=state, head=head, original=original,
                           workspace=tmp_path, wire=wire)


def _read(value):
    return read_reserved_brs_prefix(value.ledger, value.workspace, original_checkpoint=value.original,
                                    expected_checkpoint_sha256=value.head)


@pytest.mark.parametrize("outcomes", [(), ("published",), ("all_rejected",),
    ("published", "all_rejected"), ("all_rejected", "published"), ("published", "all_rejected", "published")])
def test_real_original_roots_rows_and_pins_derive_the_complete_settled_prefix(tmp_path, outcomes):
    value = _fixture(tmp_path, outcomes)
    with value.ledger.controller_lock("observed"):
        prefix, batches = _read(value)
    assert tuple(item[1] for item in prefix.settled_prefix) == outcomes
    assert len(batches) == len(outcomes)
    assert prefix.tail_checkpoint_sha256 == value.head
    assert len(json.loads(prefix.domain_bytes)["episode_ids"]) == len(outcomes) + 1
    assert value.ledger.controller_checkpoint("observed") == (value.head, value.state)


@pytest.mark.parametrize("fault", ["original-head", "original-bytes", "latest-head", "descriptor-inode", "snapshot-inode",
                                    "execution", "result", "claim"])
def test_drift_refuses_without_refreshing_the_original_capture(tmp_path, fault):
    value = _fixture(tmp_path, ("published", "all_rejected"))
    if fault == "original-head":
        value.original = _sha("foreign"), value.original[1]
    elif fault == "original-bytes":
        value.original = value.original[0], value.original[1] + b" "
    elif fault == "latest-head":
        value.head = _sha("foreign")
    elif fault in {"descriptor-inode", "snapshot-inode"}:
        filename = "before.json" if fault == "descriptor-inode" else "archive-before.snapshot"
        path = value.workspace / "evolution/producer-batches/journal-0/lineage" / filename
        raw = path.read_bytes()
        path.rename(path.with_suffix(".original"))
        path.write_bytes(raw)
        path.chmod(0o600)
    else:
        with value.ledger._connect() as connection:
            if fault == "execution":
                changed = deepcopy(value.state)
                changed["executions"][value.requests[0].episode_id]["result"]["trace_digest"] = _sha("changed")
                with value.ledger.controller_lock("observed"):
                    value.head = value.ledger.write_controller_checkpoint("observed", changed, expected_sha256=value.head)
            elif fault == "result":
                connection.execute("DELETE FROM rsi_episode_results WHERE episode_id=?", (value.requests[0].episode_id,))
            else:
                connection.execute("UPDATE rsi_native_episode_claims SET plan_sha256=? WHERE episode_id=?",
                                   (_sha("foreign"), value.requests[0].episode_id))
    with value.ledger.controller_lock("observed"), pytest.raises((RSILearningError, ValueError)):
        _read(value)


def test_prefix_observation_requires_original_controller_lease(tmp_path):
    value = _fixture(tmp_path, ())
    with pytest.raises(RSILearningError, match="controller_lock_required"):
        _read(value)


def test_private_wire_and_before_keep_both_predecessor_axes_and_old_bytes(tmp_path):
    value = _fixture(tmp_path, ("published", "all_rejected"))
    with value.ledger.controller_lock("observed"):
        prefix, _batches = _read(value)
    owner = SimpleNamespace(_reserved_prefix=prefix, _ordinal=2, _reserved_lineage_bytes=canonical_json(value.wire),
        _reserved_original_checkpoint=value.original, _reserved_capture_bytes=prefix.canonical_bytes,
        _run_id="observed", _workspace=value.workspace,
        _association={key: item for key, item in value.wire.items() if key not in {"batches", "head", "rejections"}})
    reserved_prefix_identity(owner)
    from lunar_evolution.producer_bundle_lineage import LineageSnapshotPin
    snapshots = value.wire["batches"][-1]["snapshots"]
    before = reserved_before(owner, "next-journal", *(LineageSnapshotPin.from_dict(snapshots[name])
                                                    for name in ("archive-before", "state-before")))
    reserved_verify_before_links(owner, before, ordinal=2)
    assert before.previous_attempt_journal_id == "journal-1"
    assert before.published_predecessor_journal_id == "journal-0"
    candidate = deepcopy(value.wire)
    candidate["batches"].append({"ordinal": 2})
    reserved_wire_scope(owner, candidate)
    for entry in value.wire["batches"]:
        assert reserved_verify_descriptor(owner, entry, "before").to_dict() == entry["before"]
    candidate["batches"][0]["before_file_pin"]["inode"] += 1
    with pytest.raises(RSILearningError, match="historical_prefix_drift"):
        reserved_wire_scope(owner, candidate)


@pytest.mark.parametrize("outcomes", [(), ("published", "all_rejected")])
def test_completion_prefix_reader_is_readonly_without_controller_lease(tmp_path, monkeypatch, outcomes):
    value = _fixture(tmp_path, outcomes)
    with value.ledger.controller_lock("observed"):
        expected = _read(value)
    original_connect = RSILedger._connect
    observed = []

    def connect(ledger):
        observed.append(getattr(ledger._observation_scope, "depth", 0))
        return original_connect(ledger)

    # The public readonly scope is still the concrete ledger's own implementation.
    monkeypatch.setattr(RSILedger, "_connect", connect)
    actual = read_reserved_brs_completion_prefix(value.ledger, value.workspace,
        original_checkpoint=value.original, expected_checkpoint_sha256=value.head)
    assert actual == expected
    assert observed and all(depth > 0 for depth in observed)
    with pytest.raises(RSILearningError, match="controller_lock_required"):
        _read(value)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"0", b'"text"'])
def test_malformed_original_is_a_fixed_refusal(tmp_path, raw):
    value = _fixture(tmp_path, ())
    value.original = value.original[0], raw
    with pytest.raises(RSILearningError, match="original_invalid"):
        _read(value)


def test_legacy_prefix_identity_rejects_ordinal_hook_before_equality():
    class Foreign:
        def __eq__(self, other):
            raise AssertionError("foreign equality invoked")

    owner = SimpleNamespace(_ordinal=Foreign(), _reserved_prefix=None,
        _reserved_original_checkpoint=None, _reserved_lineage_bytes=None, _reserved_capture_bytes=None)
    with pytest.raises(RSILearningError, match="capture_drift"):
        reserved_prefix_identity(owner)


@pytest.mark.parametrize("fault", ["project-and-latch", "project-cell", "projection-code"])
def test_enclosing_policy_independently_pins_the_lazy_graph_after_first_projection(monkeypatch, fault):
    import lunar_evolution.rsi_brs_publication_lineage as owner_policy
    import lunar_evolution.rsi_brs_reserved_policy as graph_policy

    owner_policy._policy()
    project = graph_policy._PROJECT
    if fault == "project-and-latch":
        entry = graph_policy.reserved_brs_policy_projection
        cache = dict(zip(entry.__code__.co_freevars, entry.__closure__, strict=True))["cache"].cell_contents
        original_pin = cache[0]

        def replacement():
            raise AssertionError("foreign project executed")

        cache[0] = (replacement, replacement.__code__, replacement.__globals__, replacement.__defaults__,
            replacement.__kwdefaults__, replacement.__closure__, ())
        monkeypatch.setattr(graph_policy, "_PROJECT", replacement)
        try:
            with pytest.raises(RSILearningError, match="reserved_policy_drift"):
                owner_policy._policy()
        finally:
            cache[0] = original_pin
    elif fault == "project-cell":
        cell = dict(zip(project.__code__.co_freevars, project.__closure__, strict=True))["fail_message"]
        original = cell.cell_contents
        cell.cell_contents = "changed-scope"
        try:
            with pytest.raises(RSILearningError, match="reserved_policy_drift"):
                owner_policy._policy()
        finally:
            cell.cell_contents = original
    else:
        monkeypatch.setattr(owner_policy._reserved_policy_projection, "__code__", (lambda: None).__code__)
        with pytest.raises(RSILearningError, match="reserved_policy_drift"):
            owner_policy._policy()
