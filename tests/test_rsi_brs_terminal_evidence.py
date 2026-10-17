"""Bounded detached reports and independent ledger projection checks.

Natural original-owner/worker terminal coverage lives in terminal_recovery. These
component fixtures deliberately cannot establish production publication authority.
"""
from __future__ import annotations

import gc
import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
import test_rsi_brs_mailbox_evidence as mailbox_fixture
from test_rsi_brs_mailbox_evidence import _append, _record
from test_rsi_brs_reconcile_controller import HEX, OTHER, _terminal_evidence

from lunar_evolution import DeterministicMockSolver, RSILearningError, RSILedger
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_reconcile import BRSReconcileEvidence, BRSReconcileObligation
from lunar_evolution.rsi_brs_terminal_evidence import (
    PROTOCOL,
    _digest,
    _ledger_terminal,
    inspect_brs_terminal_observation,
    parse_brs_terminal_observation,
)

capture = mailbox_fixture.capture


def _report():
    value = {"protocol": PROTOCOL, "run_id": "run", "episode_id": "episode", "status": "unknown",
             "reason": "mailbox_missing", "source_pins": {name: None for name in (
                 "root_checkpoint_sha256", "mailbox_checkpoint_sha256", "terminal_checkpoint_sha256",
                 "run_record_sha256", "episode_record_sha256", "native_claim_sha256", "result_sha256",
                 "obligation_sha256",
             )}, "mailbox_binding_sha256": None, "native_process_binding_sha256": None,
             "mailbox_observation": None, "callback_observation": "unobserved", "worker_terminal": False,
             "native_process_observation": None, "publication_sha256": None, "terminal_status": None,
             "evidence": None}
    value["observation_sha256"] = _digest(value)
    return value


def _ready_report():
    value = _report()
    process = {"protocol": "lunar-rsi-brs-native-process-binding-v1:observation",
               "role": "native-producer-process", "binding_sha256": HEX, "status": "exited",
               "process_state": "exited", "process_group": "absent", "observed_owner_identity": None,
               "cleanup_confirmed": True, "reason": "native_process_exited"}
    process["observation_sha256"] = _digest(process)
    evidence = BRSReconcileEvidence(
        obligation_sha256=HEX, handoff_sha256=HEX, request_sha256=HEX, native_plan_sha256=HEX,
        controller_checkpoint_sha256=HEX, episode_record_sha256=HEX, native_claim_sha256=HEX,
        process_state="exited", process_evidence_sha256=process["observation_sha256"],
        native_evidence_sha256=HEX, mailbox_evidence_sha256=HEX, result_evidence_sha256=HEX,
        mailbox_state="closed", transaction_state="terminal", terminal_status="completed",
        controller_observed_terminal=True, cleanup_confirmed=True,
    )
    value.update(status="ready", reason="independent_terminal_verified", source_pins={
        key: HEX for key in value["source_pins"]
    }, mailbox_binding_sha256=HEX, native_process_binding_sha256=HEX,
        mailbox_observation={"status": "transport_observed", "head": HEX, "terminal_evidence": False},
        callback_observation="returned", worker_terminal=True, native_process_observation=process,
        publication_sha256=HEX, terminal_status="completed", evidence=evidence.to_dict())
    value["observation_sha256"] = _digest(value)
    return value


class _Foreign:
    def __eq__(self, _other):
        pytest.fail("foreign equality hook invoked")

    def __iter__(self):
        pytest.fail("foreign iteration hook invoked")

    def __bool__(self):
        raise AssertionError("foreign truth hook invoked")

    def __repr__(self):
        pytest.fail("foreign repr hook invoked")


class _ForeignDict(dict):
    def items(self):
        pytest.fail("foreign mapping hook invoked")


@pytest.mark.parametrize("value", [_Foreign(), _ForeignDict(), float("nan"), float("inf"), 1 << 200])
def test_report_parser_rejects_foreign_and_unbounded_values_without_hooks(value):
    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_terminal_observation(value)


@pytest.mark.parametrize("field", ["status", "source_pins", "evidence", "mailbox_observation"])
def test_nested_foreign_report_values_never_execute_hooks(field):
    value = _report()
    value[field] = _Foreign()
    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_terminal_observation(value)


@pytest.mark.parametrize("mutation", [
    {"worker_terminal": 1}, {"callback_observation": "completed"}, {"terminal_status": "unknown"},
    {"reason": "contains\nnewline"}, {"publication_sha256": "arbitrary"}, {"caller_cleanup": True},
    {"status": "ready"}, {"evidence": {}},
])
def test_report_parser_rejects_unknown_flags_and_inconsistent_shape(mutation):
    value = _report() | mutation
    value["observation_sha256"] = _digest(value)
    with pytest.raises(RSILearningError):
        parse_brs_terminal_observation(value)


def test_report_is_detached_and_digest_checked():
    value = _report()
    observed = parse_brs_terminal_observation(value)
    observed["source_pins"]["root_checkpoint_sha256"] = OTHER
    assert value["source_pins"]["root_checkpoint_sha256"] is None
    value["reason"] = "different"
    with pytest.raises(RSILearningError, match="report_digest_invalid"):
        parse_brs_terminal_observation(value)


def test_selfsigned_ready_report_is_only_a_detached_observation(capture):
    """Even a coherent report cannot be supplied to the fresh inspection API."""
    value = _ready_report()
    assert parse_brs_terminal_observation(value) == value
    gc.collect()  # Finish fixture writer WAL checkpointing before observing bytes.
    before = capture.ledger.database.read_bytes()
    with pytest.raises(TypeError):
        inspect_brs_terminal_observation(
            capture.ledger, capture.run_id, capture.episode_id, workspace=None, native_plan=None,
            report=value,
        )
    observed = inspect_brs_terminal_observation(
        capture.ledger, capture.run_id, capture.episode_id, workspace=None, native_plan=None,
    )
    assert observed["status"] == "unknown" and observed["evidence"] is None
    assert capture.ledger.database.read_bytes() == before


@pytest.mark.parametrize(("field", "replacement"), [
    ("process_state", "running"), ("mailbox_state", "open"), ("transaction_state", "unknown"),
    ("controller_observed_terminal", False), ("cleanup_confirmed", False),
    ("process_evidence_sha256", OTHER), ("native_evidence_sha256", OTHER),
    ("result_evidence_sha256", OTHER), ("mailbox_evidence_sha256", OTHER),
])
def test_ready_schema_rejects_selfsigned_contradictory_evidence(field, replacement):
    value = _ready_report()
    value["evidence"][field] = replacement
    value["observation_sha256"] = _digest(value)
    with pytest.raises(RSILearningError, match="report_invalid"):
        parse_brs_terminal_observation(value)


@pytest.mark.parametrize("field", [
    "obligation_sha256", "native_claim_sha256", "result_sha256", "terminal_checkpoint_sha256",
    "mailbox_checkpoint_sha256",
])
def test_ready_schema_separates_source_pin_domains(field):
    value = _ready_report()
    value["source_pins"][field] = OTHER
    value["observation_sha256"] = _digest(value)
    with pytest.raises(RSILearningError, match="report_invalid"):
        parse_brs_terminal_observation(value)


@pytest.mark.parametrize(("field", "replacement"), [
    ("role", "brs-worker-thread"), ("process_state", "unknown"), ("status", "running"),
    ("process_group", "present"), ("cleanup_confirmed", False), ("binding_sha256", OTHER),
    ("observed_owner_identity", {"pid": 23}), ("caller_cleanup", True),
])
def test_ready_schema_keeps_native_process_and_worker_roles_separate(field, replacement):
    value = _ready_report()
    process = value["native_process_observation"]
    process[field] = replacement
    process["observation_sha256"] = _digest(process)
    value["evidence"]["process_evidence_sha256"] = process["observation_sha256"]
    value["observation_sha256"] = _digest(value)
    with pytest.raises(RSILearningError, match="report_invalid"):
        parse_brs_terminal_observation(value)


def test_ready_schema_requires_closed_domain_mailbox_and_nonmissing_pins():
    for field in ("mailbox", "run_pin"):
        value = _ready_report()
        if field == "mailbox":
            value["mailbox_observation"]["terminal_evidence"] = True
        else:
            value["source_pins"]["run_record_sha256"] = None
        value["observation_sha256"] = _digest(value)
        with pytest.raises(RSILearningError, match="report_invalid"):
            parse_brs_terminal_observation(value)


@pytest.mark.parametrize("missing", ["root_checkpoint_sha256", "result_sha256"])
def test_report_requires_exact_source_pin_domain(missing):
    value = _report()
    value["source_pins"].pop(missing)
    value["observation_sha256"] = _digest(value)
    with pytest.raises(RSILearningError, match="pins_invalid"):
        parse_brs_terminal_observation(value)


@pytest.mark.parametrize("depth", [34, 300])
def test_report_rejects_depth_before_json_recursion(depth):
    nested = {}
    for _ in range(depth):
        nested = {"nested": nested}
    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_terminal_observation(nested)


@pytest.mark.parametrize("stages", [0, 1, 2, 3, 4])
def test_missing_worker_terminal_is_readonly_and_never_observes_os(capture, monkeypatch, stages):
    value = capture
    head = None
    for index in range(stages):
        head = _append(value, _record(value, index, received=index == 3), head)
    rebuilt = RSILedger(value.ledger.database)
    gc.collect()  # Writer connections belong to setup, not the read-only subject.
    before = value.ledger.database.read_bytes()
    original = rebuilt._connect
    statements = []

    def traced():
        assert getattr(rebuilt._observation_scope, "depth", 0) > 0
        connection = original()
        connection.set_trace_callback(statements.append)
        return connection

    def forbidden(*_args, **_kwargs):
        pytest.fail("missing worker evidence must not inspect a native process")

    monkeypatch.setattr(rebuilt, "_connect", traced)
    monkeypatch.setattr("lunar_evolution.rsi_brs_terminal_evidence.observe_native_process_binding", forbidden)
    report = inspect_brs_terminal_observation(
        rebuilt, value.run_id, value.episode_id, workspace=None, native_plan=None,
    )
    assert report["status"] == "unknown" and report["evidence"] is None
    assert report["worker_terminal"] is False and report["native_process_observation"] is None
    assert report["reason"] == ("mailbox_missing" if stages == 0 else
                                "mailbox_partial" if stages < 4 else "worker_terminal_missing")
    assert value.ledger.database.read_bytes() == before
    assert statements and all(not statement.lstrip().upper().startswith(
        ("INSERT", "UPDATE", "DELETE", "CREATE", "REPLACE", "ALTER", "DROP"),
    ) for statement in statements)


def test_legitimate_root_append_during_inspection_refuses_mixed_epoch(capture, monkeypatch):
    import lunar_evolution.rsi_brs_terminal_evidence as composer

    value = capture
    original = composer.inspect_brs_mailbox_evidence

    def racing_read(*args):
        observed = original(*args)
        with value.ledger.controller_lock(value.run_id):
            head, state = value.ledger.controller_checkpoint(value.run_id)
            value.ledger.write_controller_checkpoint(value.run_id, state, expected_sha256=head)
        return observed

    monkeypatch.setattr(composer, "inspect_brs_mailbox_evidence", racing_read)
    with pytest.raises(RSILearningError, match="terminal_evidence_inspection_drift"):
        composer.inspect_brs_terminal_observation(
            value.ledger, value.run_id, value.episode_id, workspace=None, native_plan=None,
        )
    assert value.ledger.controller_brs_reconcile_obligations(value.run_id)


@pytest.mark.parametrize("keyword", ["report", "evidence", "process_state", "cleanup_confirmed", "worker_terminal"])
def test_public_inspection_accepts_no_caller_ready_report_or_terminal_flags(capture, keyword):
    with pytest.raises(TypeError):
        inspect_brs_terminal_observation(
            capture.ledger, capture.run_id, capture.episode_id, workspace=None, native_plan=None,
            **{keyword: _report()},
        )


def _terminal_snapshot(value, *, status="completed"):
    obligation = BRSReconcileObligation.from_dict(value.binding["obligation"])
    _terminal_evidence(value.ledger, value.request, obligation, status=status,
                       native_claim=False, native_result=False)
    value.ledger.publish_native_episode_result(
        value.request, plan_sha256=obligation.native_plan_sha256,
        result=DeterministicMockSolver(terminal_status=status).run(value.request), expected_claim=value.claim,
    )
    return value.ledger.read_brs_terminal_evidence_snapshot(value.run_id, value.episode_id), obligation


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "cancelled"])
def test_terminal_projection_uses_original_capture_and_real_successor(capture, status):
    snapshot, obligation = _terminal_snapshot(capture, status=status)
    original_capture = deepcopy(capture.binding)
    claim, result, result_sha = _ledger_terminal(snapshot, obligation, capture.binding)
    assert result.status == claim.status == status
    assert result_sha == snapshot["pins"]["result_sha256"]
    assert snapshot["episode_history"][-1].record_sha256 != obligation.episode_record_sha256
    assert capture.binding == original_capture


@pytest.mark.parametrize("fault", ["claim_digest", "claim_status", "saved_result_digest", "episode_projection"])
def test_terminal_projection_rejects_independent_claim_and_result_drift(capture, fault):
    snapshot, obligation = _terminal_snapshot(capture)
    if fault == "claim_digest":
        snapshot["native_claim"] = replace(snapshot["native_claim"], claim_sha256=OTHER)
    elif fault == "claim_status":
        snapshot["native_claim"] = replace(snapshot["native_claim"], status="started")
    elif fault == "saved_result_digest":
        snapshot["pins"]["result_sha256"] = OTHER
    else:
        request, result = snapshot["saved_result"]
        result = replace(result, dependency_sha256=OTHER)
        snapshot["saved_result"] = (request, result)
        snapshot["pins"]["result_sha256"] = hashlib.sha256(canonical_json(result.to_dict())).hexdigest()
    with pytest.raises(RSILearningError, match="(native_result|episode_result)_drift"):
        _ledger_terminal(snapshot, obligation, capture.binding)


@pytest.mark.parametrize("missing", ["native_claim", "saved_result"])
def test_missing_claim_or_saved_result_never_derives_terminal(capture, missing):
    snapshot, obligation = _terminal_snapshot(capture)
    snapshot[missing] = None
    assert _ledger_terminal(snapshot, obligation, capture.binding) is None
