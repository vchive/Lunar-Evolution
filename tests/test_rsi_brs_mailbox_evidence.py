"""Provider-free side-journal persistence, exact identity and read-only recovery."""
from __future__ import annotations

import hashlib
import sqlite3
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_rsi_brs_reconcile_controller import HEX, OTHER, _fixture, _register, _terminal_evidence
from test_rsi_python_brs_publication_mailbox import _ready

from lunar_evolution import DeterministicMockSolver
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_mailbox_evidence import (
    STAGES,
    brs_mailbox_evidence_namespace,
    build_brs_mailbox_binding,
    build_brs_mailbox_observation,
    inspect_brs_mailbox_evidence,
    parse_brs_mailbox_binding,
    parse_brs_mailbox_observation,
    validate_brs_mailbox_history,
)
from lunar_evolution.rsi_brs_native_process_evidence import PROTOCOL, ROLE
from lunar_evolution.rsi_brs_reconcile import FIELD, BRSReconcileObligation
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_python_brs_publication_mailbox import build_brs_owner_publication_response
from lunar_evolution.rsi_store import RSILedger


def _seal(value, field):
    value[field] = hashlib.sha256(canonical_json(
        {name: item for name, item in value.items() if name != field}, maximum=512 * 1024,
    )).hexdigest()
    return value


@pytest.fixture
def capture(tmp_path):
    ledger, run_id, episode_id, request, root, handoff, episode_sha = _fixture(tmp_path)
    run_sha = ledger.get_run(run_id).record_sha256
    claim = ledger.claim_native_episode(request, plan_sha256=HEX)
    registered = _register(
        ledger, run_id, root, handoff, episode_sha,
        expected_run_record_sha256=run_sha, expected_native_claim_sha256=claim.claim_sha256,
    )
    native = _seal({
        "protocol": PROTOCOL, "role": ROLE, "status": "unknown",
        "reason": "native_context_unavailable", "native_plan_sha256": HEX,
        "request_sha256": request.digest(), "workspace": None, "references": None, "entries": {},
    }, "binding_sha256")
    binding = build_brs_mailbox_binding(
        obligation=registered.obligation, handoff=handoff, run_record_sha256=run_sha,
        episode_record_sha256=episode_sha, native_process=native,
    )
    mailbox_request = _ready(handoff)
    response = build_brs_owner_publication_response(mailbox_request, b'{"fixture":true}')
    return SimpleNamespace(
        ledger=ledger, run_id=run_id, episode_id=episode_id, request=request,
        handoff=handoff, binding=binding, claim=claim, mailbox_request=mailbox_request,
        response=response, namespace=brs_mailbox_evidence_namespace(binding),
    )


def _record(value, index, *, received=False, root=None):
    return build_brs_mailbox_observation(
        value.binding, stage=STAGES[index],
        root_checkpoint_sha256=root or value.ledger.controller_checkpoint(value.run_id)[0],
        mailbox_state=("open", "inflight", "inflight", "delivered")[index],
        worker_receipt_observed=received,
        request=None if index == 0 else value.mailbox_request,
        response=value.response if index >= 2 else None,
    )


def _append(value, record, head=None):
    with value.ledger.controller_lock(value.run_id), value.ledger.controller_lock(value.namespace):
        return value.ledger.append_brs_mailbox_observation(
            value.binding, record, expected_sha256=head,
        )


def test_four_observations_preserve_root_fence_and_restart_inspection_writes_nothing(capture, monkeypatch):
    value = capture
    roots = value.ledger.controller_checkpoint_history(value.run_id)
    head = None
    for index in range(4):
        head = _append(value, _record(value, index, received=index == 3), head)
    assert value.ledger.controller_checkpoint_history(value.run_id) == roots
    assert value.ledger.episode_result(value.episode_id) is None
    assert value.ledger.controller_brs_reconcile_obligations(value.run_id)[value.episode_id] == value.binding["obligation"]
    rebuilt = RSILedger(value.ledger.database)
    before = value.ledger.database.read_bytes()
    original = rebuilt._connect
    statements = []

    def read_only():
        assert getattr(rebuilt._observation_scope, "depth", 0) > 0
        connection = original()
        connection.set_trace_callback(statements.append)
        return connection

    def forbidden(*_args, **_kwargs):
        pytest.fail("inspection initialized or wrote a ledger")

    monkeypatch.setattr(rebuilt, "_connect", read_only)
    monkeypatch.setattr(RSILedger, "__init__", forbidden)
    result = inspect_brs_mailbox_evidence(rebuilt, value.run_id, value.episode_id)
    assert result["status"] == "transport_observed" and result["head"] == head
    assert result["records"][-1]["worker_receipt_observed"] is True
    assert result["callback_observation"] == result["native_process_observation"] == "unobserved"
    assert result["terminal_evidence"] is False
    assert value.ledger.database.read_bytes() == before
    assert all(not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE"))
               for statement in statements)


def test_missing_and_partial_suffix_never_claim_receipt_or_callback(capture):
    value = capture
    assert inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)["status"] == "missing"
    first = _append(value, _record(value, 0))
    _append(value, _record(value, 1), first)
    result = inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)
    assert result["status"] == "partial" and result["terminal_evidence"] is False
    assert result["binding"]["capture"]["native_process"]["status"] == "unknown"
    assert result["records"][-1]["response_sha256"] is None


def test_transport_published_without_observed_worker_receipt_is_distinct(capture):
    head = None
    for index in range(4):
        head = _append(capture, _record(capture, index), head)
    record = inspect_brs_mailbox_evidence(capture.ledger, capture.run_id, capture.episode_id)["records"][-1]
    assert record["worker_receipt_observed"] is False and record["callback_observation"] == "unobserved"
    assert len({capture.binding["selected_request_sha256"], record["mailbox_request_sha256"],
                record["response_sha256"], record["response_payload_sha256"]}) == 4


@pytest.mark.parametrize("missing", ["run", "namespace"])
def test_namespace_lock_alone_or_run_lock_alone_cannot_append(capture, missing):
    value = capture
    lock = value.namespace if missing == "run" else value.run_id
    with value.ledger.controller_lock(lock), pytest.raises(RSILearningError, match="controller_lock_required"):
        value.ledger.append_brs_mailbox_observation(value.binding, _record(value, 0), expected_sha256=None)
    assert value.ledger.controller_checkpoint_history(value.namespace) == []


def test_no_cached_replay_or_latest_head_adoption(capture):
    value = capture
    initial = _record(value, 0)
    head = _append(value, initial)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _append(value, _record(value, 1), None)
    with pytest.raises(RSILearningError, match="history_invalid"):
        _append(value, initial, head)
    assert len(value.ledger.controller_checkpoint_history(value.namespace)) == 1


@pytest.mark.parametrize("fault", ["root", "obligation", "run", "episode", "claim_missing", "claim_plan", "claim_sha", "result"])
def test_atomic_writer_rejects_original_root_and_running_claim_drift(capture, fault):
    value = capture
    ledger = value.ledger
    record = _record(value, 0)
    if fault in {"root", "obligation"}:
        with ledger.controller_lock(value.run_id):
            head, state = ledger.controller_checkpoint(value.run_id)
            state = deepcopy(state)
            if fault == "obligation":
                obligation = BRSReconcileObligation.from_dict(state[FIELD][value.episode_id])
                state[FIELD][value.episode_id] = replace(obligation, worker_profile={"changed": True}).to_dict()
            else:
                state["fixture_root_progress"] = True
            next_head = ledger.write_controller_checkpoint(value.run_id, state, expected_sha256=head)
            if fault == "obligation":
                record = _record(value, 0, root=next_head)
    elif fault == "run":
        run = ledger.get_run(value.run_id)
        ledger.transition(value.run_id, state="running", expected_record_sha256=run.record_sha256,
                          payload_patch={"fixture_pin_drift": True})
    elif fault == "episode":
        prior = ledger.get_episode(value.episode_id)
        episode = PracticeEpisode.from_dict(prior.payload)
        ledger.append_episode_record(replace(
            episode, status="failed", terminal_reason="fixture", previous_record_sha256=episode.record_sha256,
        ), expected_record_sha256=prior.record_sha256)
    elif fault.startswith("claim_"):
        with sqlite3.connect(ledger.database) as connection:
            if fault == "claim_missing":
                connection.execute("DELETE FROM rsi_native_episode_claims WHERE episode_id=?", (value.episode_id,))
            else:
                field = "plan_sha256" if fault == "claim_plan" else "claim_sha256"
                connection.execute(f"UPDATE rsi_native_episode_claims SET {field}=? WHERE episode_id=?",
                                   (OTHER, value.episode_id))
    else:
        ledger.publish_native_episode_result(value.request, plan_sha256=HEX,
                                             result=DeterministicMockSolver().run(value.request),
                                             expected_claim=value.claim)
    with pytest.raises(RSILearningError, match="rsi_brs_mailbox_evidence_.*drift"):
        _append(value, record)
    assert ledger.controller_checkpoint_history(value.namespace) == []


def test_owner_pins_are_observed_under_same_sqlite_write_transaction(capture, monkeypatch):
    value = capture
    original = value.ledger._native_result_status
    observations = []

    def observe(connection, *args):
        with sqlite3.connect(value.ledger.database, timeout=0) as other, \
                pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")
        observations.append(True)
        return original(connection, *args)

    monkeypatch.setattr(value.ledger, "_native_result_status", observe)
    _append(value, _record(value, 0))
    assert observations == [True]


def test_legitimate_root_progress_does_not_refresh_immutable_capture(capture):
    value = capture
    original_binding = deepcopy(value.binding)
    first = _append(value, _record(value, 0))
    with value.ledger.controller_lock(value.run_id):
        root, state = value.ledger.controller_checkpoint(value.run_id)
        value.ledger.write_controller_checkpoint(value.run_id, state | {"fixture_progress": True}, expected_sha256=root)
    _append(value, _record(value, 1), first)
    result = inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)
    assert result["binding"] == original_binding
    assert result["records"][0]["root_checkpoint_sha256"] != result["records"][1]["root_checkpoint_sha256"]


def test_unknown_native_capture_cannot_be_backfilled_under_same_namespace(capture):
    value = capture
    head = _append(value, _record(value, 0))
    changed = deepcopy(value.binding)
    changed["capture"]["native_process"]["reason"] = "native_records_unavailable"
    _seal(changed["capture"]["native_process"], "binding_sha256")
    _seal(changed, "binding_sha256")
    assert parse_brs_mailbox_binding(changed) == changed
    assert brs_mailbox_evidence_namespace(changed) == value.namespace
    next_record = _record(value, 1)
    next_record["binding"] = changed
    next_record["binding_sha256"] = changed["binding_sha256"]
    _seal(next_record, "observation_sha256")
    with value.ledger.controller_lock(value.run_id), value.ledger.controller_lock(value.namespace), \
            pytest.raises(RSILearningError, match="binding_drift"):
        value.ledger.append_brs_mailbox_observation(changed, next_record, expected_sha256=head)


@pytest.mark.parametrize("fault", ["extra", "stage", "receipt_type", "callback", "response_early", "incomplete_pair", "queued_without_request"])
def test_strict_record_shapes_refuse_even_with_valid_recomputed_self_digest(capture, fault):
    record = _record(capture, 0)
    if fault == "extra":
        record["permit"] = True
    elif fault == "stage":
        record["stage"] = "callback_completed"
    elif fault == "receipt_type":
        record["worker_receipt_observed"] = 1
    elif fault == "callback":
        record["callback_observation"] = "completed"
    elif fault == "response_early":
        record["response_sha256"] = record["response_payload_sha256"] = HEX
    elif fault == "queued_without_request":
        record["mailbox_state"] = "queued"
    else:
        record["mailbox_request_sha256"] = HEX
    _seal(record, "observation_sha256")
    with pytest.raises(RSILearningError, match="rsi_brs_mailbox_evidence_"):
        parse_brs_mailbox_observation(record)


def test_strict_shape_gate_never_executes_foreign_container_hooks(capture):
    class Trap(dict):
        def items(self):
            pytest.fail("foreign mapping hook executed")

    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_mailbox_binding(Trap(capture.binding))


@pytest.mark.parametrize("fault", ["claim", "obligation"])
def test_rebuilt_reader_refuses_original_durable_identity_drift(capture, fault):
    value = capture
    _append(value, _record(value, 0))
    if fault == "claim":
        with sqlite3.connect(value.ledger.database) as connection:
            connection.execute("UPDATE rsi_native_episode_claims SET claim_sha256=? WHERE episode_id=?",
                               (OTHER, value.episode_id))
    else:
        with value.ledger.controller_lock(value.run_id):
            head, state = value.ledger.controller_checkpoint(value.run_id)
            obligation = BRSReconcileObligation.from_dict(state[FIELD][value.episode_id])
            state[FIELD][value.episode_id] = replace(obligation, worker_profile={}).to_dict()
            value.ledger.write_controller_checkpoint(value.run_id, state, expected_sha256=head)
    with pytest.raises(RSILearningError):
        inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)


def test_skipped_stage_cannot_be_inserted_through_generic_checkpoint_writer(capture):
    value = capture
    record = _record(value, 2)
    with value.ledger.controller_lock(value.namespace):
        value.ledger.write_controller_checkpoint(value.namespace, record, expected_sha256=None)
    with pytest.raises(RSILearningError, match="history_invalid"):
        inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)
    with pytest.raises(RSILearningError, match="history_invalid"):
        validate_brs_mailbox_history([(HEX, record)], binding=value.binding)


def test_reader_rejects_regressing_original_root_ancestors(capture):
    value = capture
    root = value.ledger.controller_checkpoint(value.run_id)[0]
    first = _append(value, _record(value, 0))
    with value.ledger.controller_lock(value.run_id):
        head, state = value.ledger.controller_checkpoint(value.run_id)
        value.ledger.write_controller_checkpoint(value.run_id, state | {"fixture_progress": True}, expected_sha256=head)
    second = _append(value, _record(value, 1), first)
    regressing = _record(value, 2, root=root)
    with value.ledger.controller_lock(value.namespace):
        value.ledger.write_controller_checkpoint(value.namespace, regressing, expected_sha256=second)
    with pytest.raises(RSILearningError, match="root_drift"):
        inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)


def test_legitimate_terminal_successor_does_not_turn_journal_inspection_into_terminal_evidence(capture):
    value = capture
    _append(value, _record(value, 0))
    obligation = BRSReconcileObligation.from_dict(value.binding["obligation"])
    _terminal_evidence(value.ledger, value.request, obligation, native_claim=False, native_result=False)
    value.ledger.publish_native_episode_result(
        value.request, plan_sha256=HEX, result=DeterministicMockSolver().run(value.request),
        expected_claim=value.claim,
    )
    result = inspect_brs_mailbox_evidence(value.ledger, value.run_id, value.episode_id)
    assert result["status"] == "partial" and result["terminal_evidence"] is False
    assert result["callback_observation"] == result["native_process_observation"] == "unobserved"


def test_original_request_capture_cannot_adopt_later_root_pins(capture):
    request = _ready(capture.handoff, head=OTHER)
    with pytest.raises(RSILearningError, match="request_invalid"):
        build_brs_mailbox_observation(
            capture.binding, stage="request_observed",
            root_checkpoint_sha256=capture.ledger.controller_checkpoint(capture.run_id)[0],
            mailbox_state="inflight", worker_receipt_observed=False, request=request,
        )


@pytest.mark.parametrize("field", ["selected_request_sha256", "native_plan_sha256", "native_claim_sha256", "episode_record_sha256"])
def test_resigned_binding_cannot_replace_original_identity(capture, field):
    changed = deepcopy(capture.binding)
    changed[field] = OTHER
    _seal(changed, "binding_sha256")
    with pytest.raises(RSILearningError, match="binding_invalid"):
        parse_brs_mailbox_binding(changed)
