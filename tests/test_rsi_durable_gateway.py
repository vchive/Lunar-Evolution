"""Local solver invocation claims never convert uncertainty into another execution."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_durable_adapter import DurableSolverGateway
from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest
from lunar_evolution.rsi_learning import RSILearningError, TraceEvent
from lunar_evolution.rsi_store import RSILedger


def request(episode_id="episode", **changes):
    values = {
        "episode_id": episode_id, "contract_sha256": "a" * 64,
        "evaluator_sha256": "b" * 64, "environment_sha256": "c" * 64,
        "memory_snapshot_sha256": "d" * 64, "solver_id": "fixture",
        "solver_settings": {"nested": {"iterations": 1}}, "budget": {"deadline_unix": 1234},
        "practice_charter": {"capability": ["local"]},
    }
    return SolverRequest.build(**(values | changes))


class Gateway:
    def __init__(self, status="completed", version=1):
        self.status, self.version = status, version
        self.calls = 0
        self.interrupt = False
        self.started = None
        self.release = None

    def rsi_fingerprint_config(self):
        return {"fixture": "durable-gateway", "status": self.status, "version": self.version}

    def run(self, request):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        if self.interrupt:
            raise RuntimeError("local fixture interrupted")
        result = DeterministicMockSolver(terminal_status=self.status).run(request)
        return replace(
            result, candidate_source_sha256="e" * 64, dependency_sha256="f" * 64,
            actor_fingerprint="1" * 64,
            trace_events=(TraceEvent(0, "tool", "local", "2" * 64, "3" * 64),),
            solver_provenance=(("fixture", {"iteration": [1, 2]}),),
        )


class OtherGateway(Gateway):
    def run(self, request):
        return Gateway.run(self, request)


class MutatingGateway(Gateway):
    def run(self, request):
        result = Gateway.run(self, request)
        dict(request.solver_settings)["nested"]["iterations"] = 99
        return result


class ConfigurationMutatingGateway(Gateway):
    def run(self, request):
        result = Gateway.run(self, request)
        self.version += 1
        return result


class WrongResultGateway(Gateway):
    def run(self, request):
        return replace(Gateway.run(self, request), request_sha256="9" * 64)


class InvalidResultGateway(Gateway):
    def run(self, request):
        self.calls += 1
        return {"status": "completed"}


def wrapper(tmp_path, gateway=None, *, scope_id="run"):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    return DurableSolverGateway(gateway or Gateway(), ledger, scope_id=scope_id)


@pytest.mark.parametrize("status", ["completed", "failed", "timed_out", "cancelled", "abandoned", "unknown"])
def test_complete_wire_replays_after_reopen_without_call_or_append(tmp_path, status):
    owner = wrapper(tmp_path, Gateway(status))
    item = request()
    result = owner.run(item)
    checkpoint = owner.inspect(item)
    assert checkpoint[1]["status"] == "completed"
    assert owner.ledger.episode_result(item.episode_id) == (item, result)
    assert owner.gateway.calls == 1
    assert result.status == status
    replay = wrapper(tmp_path, Gateway(status))
    assert replay.run(item) == result
    assert replay.restore_result(item) == result
    assert replay.gateway.calls == 0
    assert replay.inspect(item) == checkpoint
    assert result.trace_events and dict(result.solver_provenance)["fixture"] == {"iteration": [1, 2]}


def test_result_publication_crash_restores_saved_complete_wire(tmp_path, monkeypatch):
    owner = wrapper(tmp_path)
    item = request()

    def crash(*_args):
        raise RuntimeError("controller result publication interrupted")

    monkeypatch.setattr(owner.ledger, "save_episode_result", crash)
    with pytest.raises(RuntimeError, match="publication interrupted"):
        owner.run(item)
    checkpoint = owner.inspect(item)
    assert checkpoint[1]["status"] == "completed" and owner.gateway.calls == 1
    resumed = wrapper(tmp_path)
    restored = resumed.restore_result(item)
    assert resumed.ledger.episode_result(item.episode_id) == (item, restored)
    assert resumed.inspect(item) == checkpoint
    assert resumed.gateway.calls == 0


def test_started_only_exception_blocks_reexecution_and_restore(tmp_path):
    owner = wrapper(tmp_path)
    owner.gateway.interrupt = True
    item = request()
    with pytest.raises(RuntimeError, match="interrupted"):
        owner.run(item)
    checkpoint = owner.inspect(item)
    assert checkpoint[1]["status"] == "started"
    resumed = wrapper(tmp_path)
    for method in (resumed.run, resumed.restore_result):
        with pytest.raises(RSILearningError, match="rsi_durable_solver_reconcile_required"):
            method(item)
    assert resumed.gateway.calls == 0 and resumed.inspect(item) == checkpoint
    assert resumed.ledger.episode_result(item.episode_id) is None


def test_completion_append_crash_does_not_rerun_successful_delegate(tmp_path, monkeypatch):
    owner = wrapper(tmp_path)
    item = request()
    original = owner.ledger.write_controller_checkpoint

    def interrupt(namespace, state, **kwargs):
        if state.get("kind") == "durable_callback" and state.get("status") == "completed":
            raise RuntimeError("completion publication interrupted")
        return original(namespace, state, **kwargs)

    monkeypatch.setattr(owner.ledger, "write_controller_checkpoint", interrupt)
    with pytest.raises(RuntimeError, match="completion publication interrupted"):
        owner.run(item)
    assert owner.gateway.calls == 1
    resumed = wrapper(tmp_path)
    with pytest.raises(RSILearningError, match="reconcile_required"):
        resumed.run(item)
    assert resumed.gateway.calls == 0


@pytest.mark.parametrize("field,value", [
    ("contract_sha256", "9" * 64), ("evaluator_sha256", "9" * 64),
    ("environment_sha256", "9" * 64), ("memory_snapshot_sha256", "9" * 64),
    ("solver_id", "different"), ("solver_settings", {"nested": {"iterations": 2}}),
    ("budget", {"deadline_unix": 5678}), ("practice_charter", {"capability": ["changed"]}),
])
def test_same_episode_changed_request_cannot_create_second_claim(tmp_path, field, value):
    owner = wrapper(tmp_path)
    item = request()
    owner.run(item)
    checkpoint = owner.inspect(item)
    with pytest.raises(RSILearningError, match="rsi_callback_binding_drift"):
        wrapper(tmp_path).run(request(**{field: value}))
    assert owner.inspect(item) == checkpoint and owner.gateway.calls == 1


@pytest.mark.parametrize("started", [False, True])
def test_new_scope_cannot_bypass_global_episode_claim(tmp_path, started):
    owner = wrapper(tmp_path)
    owner.gateway.interrupt = started
    if started:
        with pytest.raises(RuntimeError):
            owner.run(request())
    else:
        owner.run(request())
    changed = wrapper(tmp_path, scope_id="different-run")
    with pytest.raises(RSILearningError, match="rsi_callback_binding_drift"):
        changed.run(request())
    assert changed.gateway.calls == 0


@pytest.mark.parametrize("replacement", [Gateway(version=2), OtherGateway()])
def test_new_delegate_configuration_or_code_cannot_replay_previous_claim(tmp_path, replacement):
    owner = wrapper(tmp_path)
    owner.run(request())
    changed = wrapper(tmp_path, replacement)
    with pytest.raises(RSILearningError, match="rsi_callback_binding_drift"):
        changed.run(request())
    assert replacement.calls == 0


@pytest.mark.parametrize("change", ["configuration", "callable", "scope", "ledger"])
def test_live_configuration_replacement_rejects_before_call(tmp_path, change):
    owner = wrapper(tmp_path)
    if change == "configuration":
        owner.gateway.version += 1
    elif change == "callable":
        owner.gateway.run = OtherGateway().run
    elif change == "scope":
        owner.scope_id = "different"
    else:
        owner.ledger = RSILedger(tmp_path / "other.sqlite3")
    with pytest.raises(RSILearningError, match="rsi_durable_solver_(fingerprint|configuration)_drift"):
        owner.run(request())
    assert owner.gateway.calls == 0


@pytest.mark.parametrize("gateway,code", [
    (MutatingGateway(), "request_drift"),
    (ConfigurationMutatingGateway(), "fingerprint_drift"),
    (WrongResultGateway(), "result_identity_drift"),
    (InvalidResultGateway(), "result_invalid"),
])
def test_adapter_mutation_or_invalid_result_never_publishes_completion(tmp_path, gateway, code):
    owner = wrapper(tmp_path, gateway)
    item = request()
    original_request = item.to_dict()
    with pytest.raises(RSILearningError, match="rsi_durable_solver_" + code):
        owner.run(item)
    assert item.to_dict() == original_request
    assert owner.ledger.episode_result(item.episode_id) is None
    replay = wrapper(tmp_path, type(gateway)())
    with pytest.raises(RSILearningError, match="reconcile_required"):
        replay.run(item)
    assert replay.gateway.calls == 0


def test_two_concurrent_callers_execute_exactly_once(tmp_path):
    gateway = Gateway()
    gateway.started, gateway.release = threading.Event(), threading.Event()
    first, second = wrapper(tmp_path, gateway), wrapper(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        original = pool.submit(first.run, request())
        assert gateway.started.wait(timeout=5)
        replay = pool.submit(second.run, request())
        gateway.release.set()
        result = original.result(timeout=5)
        try:
            concurrent = replay.result(timeout=5)
        except RSILearningError as exc:
            assert exc.code == "rsi_controller_busy"
        else:
            assert concurrent == result
        assert second.run(request()) == result
    assert gateway.calls == 1 and second.gateway.calls == 0


def pending(owner):
    owner.gateway.interrupt = True
    item = request()
    with pytest.raises(RuntimeError):
        owner.run(item)
    checkpoint, state = owner.inspect(item)
    return item, checkpoint, state


def evidence(state, result, **changes):
    return {
        "source": "trusted-local-failure-fixture", "binding_sha256": state["binding_sha256"],
        "result_sha256": DurableCallbackJournal.digest(result.to_dict()), "receipt_sha256": "5" * 64,
    } | changes


@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out", "abandoned"])
def test_explicit_failure_settlement_replays_without_call_or_append(tmp_path, status):
    owner = wrapper(tmp_path)
    item, checkpoint, state = pending(owner)
    result = DeterministicMockSolver(terminal_status=status).run(item)
    proof = evidence(state, result)
    settled = owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result, evidence=proof)
    completed = owner.inspect(item)
    assert settled == result
    assert owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result, evidence=proof) == result
    assert owner.restore_result(item) == result
    assert owner.run(item) == result
    assert owner.gateway.calls == 1 and owner.inspect(item) == completed


@pytest.mark.parametrize("status", ["completed", "unknown"])
def test_claimed_success_or_unknown_cannot_settle_pending_invocation(tmp_path, status):
    owner = wrapper(tmp_path)
    item, checkpoint, state = pending(owner)
    result = DeterministicMockSolver(terminal_status=status).run(item)
    with pytest.raises(RSILearningError, match="success_reconciliation_forbidden"):
        owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result, evidence=evidence(state, result))
    assert owner.inspect(item) == (checkpoint, state) and owner.gateway.calls == 1


@pytest.mark.parametrize("field,value", [
    ("source", ""), ("binding_sha256", "9" * 64), ("result_sha256", "9" * 64),
    ("receipt_sha256", "invalid"),
])
def test_reconciliation_evidence_mismatch_preserves_pending_claim(tmp_path, field, value):
    owner = wrapper(tmp_path)
    item, checkpoint, state = pending(owner)
    result = DeterministicMockSolver(terminal_status="failed").run(item)
    with pytest.raises(RSILearningError, match="rsi_callback_evidence_invalid"):
        owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result,
                        evidence=evidence(state, result, **{field: value}))
    assert owner.inspect(item) == (checkpoint, state)


def test_reconcile_changed_receipt_or_stale_cas_never_appends(tmp_path):
    owner = wrapper(tmp_path)
    item, checkpoint, state = pending(owner)
    result = DeterministicMockSolver(terminal_status="failed").run(item)
    proof = evidence(state, result)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        owner.reconcile(item, expected_checkpoint_sha256="9" * 64, result=result, evidence=proof)
    owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result, evidence=proof)
    completed = owner.inspect(item)
    with pytest.raises(RSILearningError, match="reconcile_conflict"):
        owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result,
                        evidence=proof | {"receipt_sha256": "8" * 64})
    assert owner.inspect(item) == completed


def test_missing_or_legacy_result_cannot_create_restore_or_new_call(tmp_path):
    owner = wrapper(tmp_path)
    item = request()
    with pytest.raises(RSILearningError, match="result_missing"):
        owner.restore_result(item)
    assert owner.inspect(item) is None
    result = DeterministicMockSolver().run(item)
    owner.ledger.save_episode_result(item, result)
    with pytest.raises(RSILearningError, match="unclaimed_result"):
        owner.run(item)
    assert owner.gateway.calls == 0 and owner.inspect(item) is None


def test_existing_result_conflict_does_not_overwrite_saved_wire(tmp_path, monkeypatch):
    owner = wrapper(tmp_path)
    item = request()
    original = owner.ledger.save_episode_result
    monkeypatch.setattr(owner.ledger, "save_episode_result", lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        owner.run(item)
    competing = DeterministicMockSolver(terminal_status="unknown").run(item)
    original(item, competing)
    with pytest.raises(RSILearningError, match="result_publication_conflict"):
        owner.restore_result(item)
    assert owner.ledger.episode_result(item.episode_id) == (item, competing)
    assert owner.gateway.calls == 1


def test_database_same_bytes_replacement_rejects(tmp_path):
    owner = wrapper(tmp_path)
    owner.run(request())
    database = owner.ledger.database
    replacement = database.with_name("replacement.sqlite3")
    replacement.write_bytes(database.read_bytes())
    replacement.replace(database)
    with pytest.raises(RSILearningError, match="fingerprint_drift"):
        owner.restore_result(request())


def test_independent_episode_ids_each_have_one_invocation(tmp_path):
    owner = wrapper(tmp_path)
    one, two = request("one"), request("two")
    owner.run(one)
    owner.run(two)
    owner.run(one)
    owner.run(two)
    assert owner.gateway.calls == 2


def test_completed_replay_never_writes_existing_result_or_claim(tmp_path, monkeypatch):
    owner = wrapper(tmp_path)
    item = request()
    result = owner.run(item)
    checkpoint = owner.inspect(item)

    def forbidden(*_args, **_kwargs):
        pytest.fail("a completed replay must not append any result or claim")

    monkeypatch.setattr(owner.ledger, "save_episode_result", forbidden)
    monkeypatch.setattr(owner.ledger, "write_controller_checkpoint", forbidden)
    assert owner.run(item) == result
    assert owner.restore_result(item) == result
    assert owner.inspect(item) == checkpoint


def test_returned_nested_result_cannot_mutate_persisted_evidence(tmp_path):
    owner = wrapper(tmp_path)
    item = request()
    result = owner.run(item)
    checkpoint = owner.inspect(item)
    dict(result.solver_provenance)["fixture"]["iteration"].append(99)
    restored = owner.restore_result(item)
    assert dict(restored.solver_provenance)["fixture"]["iteration"] == [1, 2]
    assert owner.inspect(item) == checkpoint and owner.gateway.calls == 1


def test_failure_settlement_must_match_the_original_request(tmp_path):
    owner = wrapper(tmp_path)
    item, checkpoint, state = pending(owner)
    result = DeterministicMockSolver(terminal_status="failed").run(item)
    result = replace(result, request_sha256="9" * 64)
    with pytest.raises(RSILearningError, match="result_identity_drift"):
        owner.reconcile(item, expected_checkpoint_sha256=checkpoint, result=result, evidence=evidence(state, result))
    assert owner.inspect(item) == (checkpoint, state)


def test_delegate_without_stable_identity_is_rejected(tmp_path):
    class UnidentifiedGateway:
        def run(self, item):
            pytest.fail("unidentified delegate must not execute")

    with pytest.raises(RSILearningError, match="fingerprint_invalid"):
        wrapper(tmp_path, UnidentifiedGateway())


@pytest.mark.parametrize("scope_id", ["", "  ", "scope\nother", "scope\x00other", "x" * 4097])
def test_invalid_scope_cannot_create_wrapper(tmp_path, scope_id):
    with pytest.raises(RSILearningError, match="configuration_invalid"):
        wrapper(tmp_path, scope_id=scope_id)
