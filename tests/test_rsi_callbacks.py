"""Durable local callback execution, quarantine, and explicit reconciliation."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

BINDING = {"input": {"episode": "practice-1"}, "component_sha256": "a" * 64}
RESULT = {"verdict": "passed", "score": 1}


class CallbackCrash(BaseException):
    pass


def validate(result):
    if set(result) != {"verdict", "score"} or result["verdict"] not in {"passed", "failed"}:
        raise RSILearningError("test_invalid_result")


def crash():
    raise CallbackCrash()


@pytest.fixture
def journal(tmp_path):
    return DurableCallbackJournal(RSILedger(tmp_path / "rsi.db"))


def invoke(journal, *, call=lambda: RESULT, binding=BINDING, **kwargs):
    return journal.invoke("run-1", "verifier:practice-1", binding=binding,
                          call=call, validate=validate, **kwargs)


def inspect(journal):
    return journal.inspect("run-1", "verifier:practice-1")


def evidence(result=RESULT, binding=BINDING):
    return {
        "source": "local-test-receipt", "receipt_sha256": "b" * 64,
        "binding_sha256": DurableCallbackJournal.digest(binding),
        "result_sha256": DurableCallbackJournal.digest(result),
        "operator_note": {"fixture_only": True},
    }


def reconcile(journal, digest, *, result=RESULT, binding=BINDING, proof=None):
    return journal.reconcile(
        "run-1", "verifier:practice-1", expected_checkpoint_sha256=digest,
        binding=binding, result=result, evidence=proof or evidence(result, binding), validate=validate,
    )


def start_uncertain(journal):
    with pytest.raises(CallbackCrash):
        invoke(journal, call=crash)
    digest, state = inspect(journal)
    assert state["status"] == "started"
    return digest


def test_completed_replays_from_fresh_ledger_without_callback_or_deadline(journal):
    events = []

    def call():
        events.append("called")
        assert inspect(journal)[1]["status"] == "started"
        return RESULT

    assert invoke(journal, call=call) == RESULT
    fresh = DurableCallbackJournal(RSILedger(journal.ledger.database))
    assert invoke(fresh, call=crash, before_call=crash) == RESULT
    assert events == ["called"]
    assert len(journal.ledger.controller_checkpoint_history(
        journal.identity("run-1", "verifier:practice-1"),
    )) == 2


def test_started_callback_never_automatically_retried(journal):
    initial = start_uncertain(journal)
    with pytest.raises(RSILearningError, match="^rsi_callback_reconcile_required$"):
        invoke(journal, call=crash)
    assert inspect(journal)[0] == initial


def test_crash_after_result_before_publish_requires_reconcile(journal, monkeypatch):
    original = journal.ledger.write_controller_checkpoint
    calls = []

    def write(namespace, state, *, expected_sha256):
        if state["status"] == "completed":
            raise CallbackCrash()
        return original(namespace, state, expected_sha256=expected_sha256)

    monkeypatch.setattr(journal.ledger, "write_controller_checkpoint", write)
    with pytest.raises(CallbackCrash):
        invoke(journal, call=lambda: calls.append("effect") or RESULT)
    monkeypatch.setattr(journal.ledger, "write_controller_checkpoint", original)
    with pytest.raises(RSILearningError, match="rsi_callback_reconcile_required"):
        invoke(journal, call=lambda: calls.append("again") or RESULT)
    started_digest, _ = inspect(journal)
    assert reconcile(journal, started_digest) == RESULT
    assert invoke(journal, call=crash) == RESULT
    assert calls == ["effect"]


def test_reconcile_is_idempotent_for_original_or_current_digest(journal):
    started_digest = start_uncertain(journal)
    assert reconcile(journal, started_digest) == RESULT
    completed_digest, state = inspect(journal)
    assert state["reconciliation"] == evidence()
    assert state["started_checkpoint_sha256"] == started_digest
    assert reconcile(journal, started_digest) == RESULT
    assert reconcile(journal, completed_digest) == RESULT
    assert inspect(journal)[0] == completed_digest


@pytest.mark.parametrize("changed", ["evidence", "evidence_type", "result", "cas"])
def test_completed_reconcile_rejects_conflicts(journal, changed):
    started_digest = start_uncertain(journal)
    reconcile(journal, started_digest)
    original = inspect(journal)
    kwargs = {}
    expected_error = "rsi_callback_reconcile_conflict"
    if changed == "evidence":
        kwargs["proof"] = {**evidence(), "source": "different-source"}
    elif changed == "evidence_type":
        kwargs["proof"] = {**evidence(), "operator_note": {"fixture_only": 1}}
    elif changed == "result":
        kwargs["result"] = {"verdict": "failed", "score": 0}
    else:
        started_digest = "f" * 64
        expected_error = "rsi_callback_checkpoint_conflict"
    with pytest.raises(RSILearningError, match=expected_error):
        reconcile(journal, started_digest, **kwargs)
    assert inspect(journal) == original


def test_ordinary_completion_cannot_be_rewritten_as_reconciliation(journal):
    invoke(journal)
    digest, _ = inspect(journal)
    with pytest.raises(RSILearningError, match="rsi_callback_reconcile_conflict"):
        reconcile(journal, digest)


def test_reconcile_requires_started_identity_and_exact_cas(journal):
    with pytest.raises(RSILearningError, match="rsi_callback_not_started"):
        reconcile(journal, "0" * 64)
    initial = start_uncertain(journal)
    with pytest.raises(RSILearningError, match="rsi_callback_checkpoint_conflict"):
        reconcile(journal, "0" * 64)
    assert inspect(journal)[0] == initial


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("field", ["input", "component_sha256"])
def test_binding_drift_rejected_before_call_and_reconcile(journal, completed, field):
    if completed:
        invoke(journal)
    else:
        start_uncertain(journal)
    original = inspect(journal)
    changed = {**BINDING, field: "drift"}
    with pytest.raises(RSILearningError, match="rsi_callback_binding_drift"):
        invoke(journal, call=crash, binding=changed)
    with pytest.raises(RSILearningError, match="rsi_callback_binding_drift"):
        reconcile(journal, original[0], binding=changed)
    assert inspect(journal) == original


@pytest.mark.parametrize("field,value", [
    ("source", ""), ("source", " "), ("source", None), ("source", "line\nbreak"),
    ("binding_sha256", "f" * 64), ("result_sha256", "f" * 64),
    ("receipt_sha256", "f" * 63), ("receipt_sha256", "F" * 64), ("receipt_sha256", None),
])
def test_invalid_reconcile_evidence_does_not_change_started(journal, field, value):
    initial = start_uncertain(journal)
    proof = {**evidence(), field: value}
    with pytest.raises(RSILearningError, match="rsi_callback_evidence_invalid"):
        reconcile(journal, initial, proof=proof)
    assert inspect(journal)[0] == initial


def test_validate_evidence_is_read_only_and_returns_detached_copy(journal):
    proof = evidence()
    clean = journal.validate_evidence(BINDING, RESULT, proof)
    clean["operator_note"]["fixture_only"] = False
    assert proof["operator_note"]["fixture_only"] is True
    assert inspect(journal) is None
    with pytest.raises(RSILearningError, match="rsi_callback_evidence_invalid"):
        journal.validate_evidence(BINDING, {"verdict": "failed"}, proof)


def test_semantically_invalid_result_remains_started(journal):
    with pytest.raises(RSILearningError, match="test_invalid_result"):
        invoke(journal, call=lambda: {"unexpected": "wire"})
    initial = inspect(journal)[0]
    with pytest.raises(RSILearningError, match="test_invalid_result"):
        reconcile(journal, initial, result={"unexpected": "wire"})
    assert inspect(journal)[0] == initial
    with pytest.raises(RSILearningError, match="rsi_callback_reconcile_required"):
        invoke(journal, call=crash)


def test_replay_still_validates_semantic_result(journal):
    invoke(journal)
    original = inspect(journal)
    with pytest.raises(CallbackCrash):
        journal.invoke("run-1", "verifier:practice-1", binding=BINDING,
                       call=crash, validate=lambda result: crash())
    assert inspect(journal) == original


def test_validator_cannot_mutate_durable_result(journal):
    result = journal.invoke("run-1", "verifier:practice-1", binding=BINDING,
                            call=lambda: RESULT, validate=lambda result: result.clear())
    assert result == RESULT
    result.clear()
    assert inspect(journal)[1]["result"] == RESULT


@pytest.mark.parametrize("value", [
    {"bad": float("nan")}, {1: "integer key"}, {"tuple": (1,)}, {"set": {1}},
])
def test_non_json_binding_never_starts_callback(journal, value):
    with pytest.raises(RSILearningError, match="rsi_callback_binding_invalid"):
        invoke(journal, binding=value, call=crash)
    assert inspect(journal) is None


def test_oversized_input_or_output_does_not_allow_retry(journal):
    with pytest.raises(RSILearningError, match="rsi_callback_binding_invalid"):
        invoke(journal, binding={"large": "x" * (512 * 1024)}, call=crash)
    assert inspect(journal) is None
    with pytest.raises(RSILearningError, match="rsi_callback_result_invalid"):
        invoke(journal, call=lambda: {"large": "x" * (1024 * 1024)})
    assert inspect(journal)[1]["status"] == "started"


def test_before_call_runs_under_lock_before_started_checkpoint(journal):
    def reject_deadline():
        assert journal.ledger.controller_lock_held(journal.identity("run-1", "verifier:practice-1"))
        assert inspect(journal) is None
        raise RSILearningError("deadline_exceeded")

    with pytest.raises(RSILearningError, match="deadline_exceeded"):
        invoke(journal, call=crash, before_call=reject_deadline)
    assert inspect(journal) is None


def test_concurrent_invoke_and_reconcile_cannot_duplicate_callback(journal):
    entered, release = Event(), Event()
    calls = []

    def call():
        calls.append("call")
        entered.set()
        assert release.wait(timeout=10)
        return RESULT

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke, journal, call=call)
        assert entered.wait(timeout=10)
        try:
            other = DurableCallbackJournal(RSILedger(journal.ledger.database))
            started_digest = inspect(other)[0]
            with pytest.raises(RSILearningError, match="rsi_controller_busy"):
                invoke(other, call=crash)
            with pytest.raises(RSILearningError, match="rsi_controller_busy"):
                reconcile(other, started_digest)
        finally:
            release.set()
        assert future.result(timeout=10) == RESULT
    assert calls == ["call"]


def test_scope_and_callback_names_have_unambiguous_private_namespaces(journal):
    identities = {
        journal.identity("run:a", "b"), journal.identity("run", "a:b"),
        journal.identity("run", "a"), journal.identity("other", "a"),
    }
    assert len(identities) == 4
    assert all(identity.startswith("rsi-callback:") for identity in identities)
    assert journal.identity("../run", "../../callback").count("/") == 0
    with pytest.raises(RSILearningError, match="rsi_callback_identity_invalid"):
        journal.identity("run\x00", "callback")


def test_hash_chain_tampering_is_detected(journal):
    start_uncertain(journal)
    with sqlite3.connect(journal.ledger.database) as connection:
        connection.execute("UPDATE rsi_controller_journal SET payload = ?", ('{"tampered":true}',))
    with pytest.raises(RSILearningError, match="rsi_controller_checkpoint_corrupt"):
        inspect(journal)


@pytest.mark.parametrize("mutation", ["extra", "missing", "status", "binding", "transition", "parent"])
def test_semantically_forged_checkpoints_rejected_even_with_recomputed_hash(journal, mutation):
    invoke(journal)
    namespace = journal.identity("run-1", "verifier:practice-1")
    history = journal.ledger.controller_checkpoint_history(namespace)
    states = [deepcopy(state) for _, state in history]
    if mutation == "extra":
        states[1]["extra"] = True
    elif mutation == "missing":
        states[1].pop("reconciliation")
    elif mutation == "status":
        states[1]["status"] = []
    elif mutation == "binding":
        states[1]["binding"] = {"tampered": True}
        states[1]["binding_sha256"] = journal.digest(states[1]["binding"])
    elif mutation == "transition":
        states[1] = deepcopy(states[0])
    else:
        states[1]["started_checkpoint_sha256"] = "0" * 64
    with sqlite3.connect(journal.ledger.database) as connection:
        parent = None
        for revision, state in enumerate(states):
            digest = journal.ledger._checkpoint_digest(namespace, revision, parent, state)
            connection.execute(
                "UPDATE rsi_controller_journal SET payload = ?, checkpoint_sha256 = ?, "
                "parent_sha256 = ? WHERE run_id = ? AND revision = ?",
                (json.dumps(state), digest, parent, namespace, revision),
            )
            parent = digest
    with pytest.raises(RSILearningError, match="rsi_callback_checkpoint_corrupt"):
        inspect(journal)


def test_extra_checkpoint_revision_rejected(journal):
    invoke(journal)
    digest, state = inspect(journal)
    namespace = journal.identity("run-1", "verifier:practice-1")
    with journal.ledger.controller_lock(namespace):
        journal.ledger.write_controller_checkpoint(namespace, state, expected_sha256=digest)
    with pytest.raises(RSILearningError, match="rsi_callback_checkpoint_corrupt"):
        inspect(journal)
