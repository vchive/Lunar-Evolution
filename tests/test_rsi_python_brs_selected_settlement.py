"""Owner checkpoint settlement over real inert BRS ready/ACK and durable results.

The selected-service fixture executes only a local inert gateway. Successful
checkpoint CAS and readback use the actual controller and SQLite ledger; fault
injection below is confined to refusal and unknown-return boundaries.
"""

from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest
import test_rsi_python_brs_selected_service as selected_service
from test_rsi_python_admission import OTHER, _rows
from test_rsi_python_admission_flow import _forged_checkpoint_append
from test_rsi_python_brs_selected_service import (
    _evidence_files,
    _fixture,
    _wave,
)

from lunar_evolution import RSILearningError, rsi_controller
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_fingerprint import RSIFingerprintError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan

no_external_execution = selected_service.no_external_execution


def _returned(value, wave):
    record = value.ledger.get_run(value.binding.run_id)
    execution = value.controller._python_admission_run_selected_brs_intent(wave)
    assert wave.channel._closed
    assert wave.channel._completed_selected_episodes == {value.episode_id}
    assert wave.channel._requests[value.episode_id].ack is not None
    assert value.ledger.get_episode(value.episode_id).payload == execution.episode.to_record_dict()
    assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
    return record, execution


def _settle(value, record, wave, execution):
    return value.controller._python_admission_settle_selected_brs_execution(record, wave, execution)


def _consume_original_solver_budget_for_fault(wave):
    budget = RSIRunBudget.load(wave.budget_state)
    before = budget.to_dict()
    budget.consume("solver_invocations")
    changed = budget.to_dict()
    assert changed["consumed"]["solver_invocations"] == before["consumed"]["solver_invocations"] + 1
    if before["remaining"]["solver_invocations"] is None:
        assert changed["remaining"]["solver_invocations"] is None
    else:
        assert changed["remaining"]["solver_invocations"] == before["remaining"]["solver_invocations"] - 1
    wave.budget_state.clear()
    wave.budget_state.update(changed)
    assert RSIRunBudget.load(wave.budget_state).to_dict() == changed


def _assert_single_worker(value):
    assert value.gateway.calls == 1
    assert value.ledger.get_episode(value.sibling_id) is None
    assert value.ledger.episode_result(value.sibling_id) is None
    assert len(_rows(value)["rsi_python_admissions"]) == 1


def _refused(value, wave, operation, *, match):
    rows, files = _rows(value), _evidence_files(value)
    state, budget = deepcopy(wave.state), deepcopy(wave.budget_state)
    head, payload = wave.checkpoint_sha256, wave.payload
    with pytest.raises((RSILearningError, RSIFingerprintError), match=match) as caught:
        operation()
    assert _rows(value) == rows
    assert _evidence_files(value) == files
    assert wave.state == state and wave.budget_state == budget
    assert wave.checkpoint_sha256 == head and wave.payload == payload
    _assert_single_worker(value)
    return caught.value


def test_owner_settlement_adds_only_selected_execution_by_real_cas_and_readback(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        original = deepcopy(wave.state)
        rows, files = _rows(value), _evidence_files(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        expected = deepcopy(original)
        expected["executions"][value.episode_id] = {
            "episode": execution.episode.to_record_dict(),
            "request": execution.request.to_dict(),
            "result": execution.result.to_dict(),
            "verifier": execution.verifier.to_dict(),
        }
        expected.update(phase="evaluated", current_episode_id=value.episode_id)
        head = _settle(value, record, wave, execution)
        assert type(head) is str and head != history[-1][0]
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (head, expected)
        assert wave.state == expected and wave.checkpoint_sha256 == head
        assert wave.payload == value.controller._python_admission_flow_payload(expected)
        assert wave.budget_state == original["budget_state"] == expected["budget_state"]
        after = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert after[:-1] == history and after[-1] == (head, expected)
        after_rows = _rows(value)
        assert after_rows["rsi_controller_journal"][:-1] == rows["rsi_controller_journal"]
        assert {key: item for key, item in after_rows.items() if key != "rsi_controller_journal"} == {
            key: item for key, item in rows.items() if key != "rsi_controller_journal"
        }
        assert _evidence_files(value) == files
        assert value.ledger.get_run(value.binding.run_id) == record
        _assert_single_worker(value)
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


def test_owner_result_acceptance_refuses_stale_controller_checkpoint(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        _record, execution = _returned(value, wave)
        reference = wave.state["python_admission_refs"][value.episode_id]
        plan = NativeRSIExecutionPlan.from_dict(reference["native_plan"])
        claim = value.ledger.inspect_native_episode_claim(
            execution.request, plan_sha256=plan.plan_sha256,
        )
        assert claim is not None
        with pytest.raises(RSILearningError, match="controller_checkpoint_conflict"):
            value.ledger.accept_native_episode_result(
                execution.request,
                plan_sha256=plan.plan_sha256,
                result=execution.result,
                expected_claim=claim,
                controller_run_id=value.binding.run_id,
                expected_controller_checkpoint_sha256=OTHER,
                expected_episode_record_sha256=execution.episode.record_sha256,
            )
        assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)


def test_settlement_source_hooks_and_real_save_do_not_hold_observation_mutex(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave, ThreadPoolExecutor(max_workers=1) as observer:
        record, execution = _returned(value, wave)
        original_config = value.gateway.rsi_fingerprint_config
        original_save = value.controller._save_flow
        observed = []

        def observe():
            with value.controller._python_admission_brs_observations():
                return True

        def source_config():
            assert observer.submit(observe).result(timeout=4)
            observed.append("source")
            return original_config()

        def save(*args, **kwargs):
            assert observer.submit(observe).result(timeout=4)
            observed.append("save")
            return original_save(*args, **kwargs)

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_config)
        monkeypatch.setattr(value.controller, "_save_flow", save)
        head = _settle(value, record, wave, execution)
        assert "source" in observed and observed.count("save") == 1
        assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == head
        _assert_single_worker(value)


def test_foreign_thread_cannot_settle_owner_return(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave, ThreadPoolExecutor(max_workers=1) as pool:
        record, execution = _returned(value, wave)

        def invoke():
            return pool.submit(_settle, value, record, wave, execution).result(timeout=10)

        _refused(value, wave, invoke, match="^rsi_python_brs_admission_identity_invalid$")


@pytest.mark.parametrize("fault", ["type", "run", "head", "state", "request", "payload", "durable_head"])
def test_owner_settlement_rejects_foreign_or_stale_run_record(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        if fault == "type":
            record = object()
        elif fault == "durable_head":
            latest = value.ledger.transition(
                value.binding.run_id, state="running", expected_record_sha256=record.record_sha256,
            )
            assert latest.record_sha256 != record.record_sha256
        else:
            fields = {"run": {"logical_id": "foreign-run"}, "head": {"record_sha256": OTHER},
                      "state": {"state": "unknown"}, "request": {"request_sha256": OTHER},
                      "payload": {"payload": {**record.payload, "mode": "drs"}}}
            record = replace(record, **fields[fault])
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_record_invalid$")


@pytest.mark.parametrize("fault", ["clone", "type", "request", "result", "episode", "verifier"])
def test_owner_settlement_requires_exact_unchanged_service_return(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        if fault == "clone":
            original = execution
            execution = replace(execution)
            assert execution == original and execution is not original
        elif fault == "type":
            execution = object()
        else:
            changed = {
                "request": lambda: replace(execution.request, episode_id=value.sibling_id),
                "result": lambda: replace(execution.result, trace_digest=OTHER),
                "episode": lambda: replace(execution.episode, memory_snapshot_sha256=OTHER),
                "verifier": lambda: replace(execution.verifier, diagnosis="foreign-verifier"),
            }[fault]()
            object.__setattr__(execution, fault, changed)
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_result_invalid$")


@pytest.mark.parametrize("fault", ["source", "m0", "budget", "request_budget", "head"])
def test_owner_settlement_rechecks_original_pins_without_refresh_or_repair(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        if fault == "source":
            value.gateway.fingerprint = "foreign-settlement-source"
            match = "fingerprint"
        elif fault == "m0":
            object.__setattr__(wave.selected_handoff, "root_snapshot_sha256", OTHER)
            match = "^rsi_python_brs_admission_selected_identity_invalid$"
        elif fault == "budget":
            wave.budget_state["planned"]["deadline_unix"] += 1
            match = "stale|budget"
        elif fault == "request_budget":
            wave.state["intents"][value.episode_id]["request"]["budget"]["deadline_unix"] += 1
            match = "stale|budget"
        else:
            _forged_checkpoint_append(value, lambda state: state.update(phase="foreign-head"))
            match = "^rsi_python_brs_admission_stale$"
        _refused(value, wave, lambda: _settle(value, record, wave, execution), match=match)


def test_owner_settlement_checks_retained_deadline_and_never_allocates_new_budget(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        original_budget = deepcopy(wave.budget_state)
        monkeypatch.setattr(rsi_controller.time, "time", lambda: value.binding.deadline_unix)
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_budget_exhausted$")
        assert wave.budget_state == wave.state["budget_state"] == original_budget


@pytest.mark.parametrize("fault", ["planned", "consumed", "record_state", "record_payload"])
def test_source_hook_cannot_change_original_owner_inputs_between_entry_and_write(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        original_state = deepcopy(wave.state)
        rows, files = _rows(value), _evidence_files(value)
        original_head, original_payload = wave.checkpoint_sha256, wave.payload
        original_config = value.gateway.rsi_fingerprint_config
        injected = {}

        def source_config():
            if not injected:
                if fault == "planned":
                    wave.budget_state["planned"]["deadline_unix"] += 1
                elif fault == "consumed":
                    _consume_original_solver_budget_for_fault(wave)
                elif fault == "record_state":
                    object.__setattr__(record, "state", "unknown")
                else:
                    assert fault == "record_payload"
                    record.payload["mode"] = "drs"
                injected["budget"] = deepcopy(wave.budget_state)
            return original_config()

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source_config)
        suffix = "selected_settlement_record_invalid" if fault.startswith("record_") else "selected_budget_invalid"
        with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_" + suffix + "$"):
            _settle(value, record, wave, execution)
        assert injected and _rows(value) == rows and _evidence_files(value) == files
        assert wave.state == original_state and wave.budget_state == injected["budget"]
        assert (wave.budget_state != wave.state["budget_state"]) is (not fault.startswith("record_"))
        assert (wave.checkpoint_sha256, wave.payload) == (original_head, original_payload)
        _assert_single_worker(value)


@pytest.mark.parametrize("fault", ["missing", "run", "episode", "request", "record", "fields"])
def test_owner_settlement_rechecks_retained_ready_ack_after_service_closed(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        pending = wave.channel._requests[value.episode_id]
        if fault == "missing":
            pending.ack = None
        elif fault == "fields":
            pending.ack_fields = (*pending.ack_fields[:3], OTHER)
        else:
            field = {"run": "run_id", "episode": "episode_id", "request": "request_sha256",
                     "record": "record_sha256"}[fault]
            object.__setattr__(pending.ack, field, "foreign-id" if fault in {"run", "episode"} else OTHER)
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_ack_invalid$")


def test_owner_settlement_without_original_successful_return_receipt_is_unavailable(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        wave.selected_return = None
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


def test_real_executor_join_failure_cannot_mint_return_or_settle_completed_result(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    futures = []

    class JoinedThenFailedExecutor(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            future = super().submit(*args, **kwargs)
            futures.append(future)
            return future

        def shutdown(self, wait=True, *, cancel_futures=False):
            assert wait and wave.channel._closed
            super().shutdown(wait=wait, cancel_futures=cancel_futures)
            assert len(futures) == 1 and futures[0].done()
            assert futures[0].exception() is None
            raise RuntimeError("inert-shutdown-failure-after-real-join")

    monkeypatch.setattr(rsi_controller, "ThreadPoolExecutor", JoinedThenFailedExecutor)
    with _wave(value) as wave:
        record = value.ledger.get_run(value.binding.run_id)
        with pytest.raises(RuntimeError, match="^inert-shutdown-failure-after-real-join$"):
            value.controller._python_admission_run_selected_brs_intent(wave)
        execution = futures[0].result()
        assert wave.channel._closed and wave.selected_return is None
        assert wave.channel._completed_selected_episodes == {value.episode_id}
        assert wave.channel._requests[value.episode_id].ack is not None
        assert value.ledger.get_episode(value.episode_id).payload == execution.episode.to_record_dict()
        assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
        _, durable = value.ledger.controller_checkpoint(value.binding.run_id)
        assert durable == wave.state and durable["executions"] == {}
        assert set(durable["python_admission_refs"]) == {value.episode_id}
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


def test_inactive_owner_wave_cannot_publish_selected_execution(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
    assert not wave.active
    _refused(value, wave, lambda: _settle(value, record, wave, execution),
             match="^rsi_python_brs_admission_identity_invalid$")


def test_owner_settlement_real_cas_race_retains_winner_and_poisoned_return(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        original_state = deepcopy(wave.state)
        original_head, original_payload = wave.checkpoint_sha256, wave.payload
        original_write = value.ledger.write_controller_checkpoint
        raced = {}

        def write(run_id, state, *, expected_sha256):
            assert not raced and expected_sha256 == original_head
            head = original_write(run_id, deepcopy(original_state), expected_sha256=original_head)
            assert head != original_head
            raced.update(head=head, rows=_rows(value))
            return original_write(run_id, state, expected_sha256=expected_sha256)

        with monkeypatch.context() as patch:
            patch.setattr(value.ledger, "write_controller_checkpoint", write)
            with pytest.raises(RSILearningError, match="checkpoint_conflict"):
                _settle(value, record, wave, execution)
        assert raced and _rows(value) == raced["rows"]
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (raced["head"], original_state)
        assert wave.state == original_state
        assert (wave.checkpoint_sha256, wave.payload) == (original_head, original_payload)
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


@pytest.mark.parametrize("fault", [
    "readback_head", "readback_payload", "unknown_save_return", "source", "m0", "ack",
    "durable_episode", "durable_result", "receipt", "execution", "handoff",
    "budget_planned", "budget_consumed", "caller_record", "source_and_record",
])
def test_owner_settlement_unknown_commit_retains_durable_progress_without_retry(tmp_path, monkeypatch, fault):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        original_state = deepcopy(wave.state)
        original_head, original_payload = wave.checkpoint_sha256, wave.payload
        original_save = value.controller._save_flow
        committed = {}
        files = _evidence_files(value)

        def save(*args, **kwargs):
            head = original_save(*args, **kwargs)
            durable = value.ledger.controller_checkpoint(value.binding.run_id)
            assert durable[0] == head != original_head
            assert set(durable[1]["executions"]) == {value.episode_id}
            committed.update(head=head, durable=deepcopy(durable), rows=_rows(value))
            if fault == "unknown_save_return":
                raise RSILearningError("fixture_settlement_save_return_unknown")
            if fault in {"readback_head", "readback_payload"}:
                changed = deepcopy(durable[1])
                changed["current_episode_id"] = value.sibling_id
                observation = (OTHER, durable[1]) if fault == "readback_head" else (head, changed)
                patch.setattr(value.ledger, "controller_checkpoint", lambda run_id: deepcopy(observation))
            elif fault in {"source", "source_and_record"}:
                value.gateway.fingerprint = "foreign-post-save-source"
                if fault == "source_and_record":
                    object.__setattr__(record, "state", "unknown")
            elif fault == "m0":
                object.__setattr__(wave.selected_handoff, "root_snapshot_sha256", OTHER)
            elif fault == "ack":
                object.__setattr__(wave.channel._requests[value.episode_id].ack, "record_sha256", OTHER)
            elif fault == "durable_episode":
                previous = value.ledger.get_episode(value.episode_id)
                changed = replace(execution.episode, trace_digest=OTHER,
                                  previous_record_sha256=execution.episode.record_sha256)
                value.ledger.append_episode_record(changed, expected_record_sha256=previous.record_sha256)
            elif fault == "durable_result":
                changed = canonical_json(replace(execution.result, trace_digest=OTHER).to_dict())
                with sqlite3.connect(value.ledger.database) as connection:
                    connection.execute(
                        "UPDATE rsi_episode_results SET result_payload=?,result_sha256=? WHERE episode_id=?",
                        (changed.decode(), hashlib.sha256(changed).hexdigest(), value.episode_id),
                    )
            elif fault == "receipt":
                wave.selected_return = replace(wave.selected_return, execution_payload=b"{}")
            elif fault == "execution":
                object.__setattr__(execution, "result", replace(execution.result, trace_digest=OTHER))
            elif fault == "handoff":
                object.__setattr__(wave.selected_handoff, "lease_nonce", "X" * 32)
            elif fault == "budget_planned":
                wave.budget_state["planned"]["deadline_unix"] += 1
            elif fault == "caller_record":
                object.__setattr__(record, "state", "unknown")
            else:
                assert fault == "budget_consumed"
                _consume_original_solver_budget_for_fault(wave)
            committed.update(rows=_rows(value), budget=deepcopy(wave.budget_state))
            return head

        with monkeypatch.context() as patch:
            patch.setattr(value.controller, "_save_flow", save)
            if fault == "readback_head":
                match = "^rsi_python_admission_checkpoint_conflict$"
            elif fault == "unknown_save_return":
                match = "^fixture_settlement_save_return_unknown$"
            elif fault in {"source", "source_and_record"}:
                match = "fingerprint"
            elif fault in {"m0", "handoff"}:
                match = "^rsi_python_brs_admission_selected_identity_invalid$"
            elif fault == "ack":
                match = "^rsi_python_brs_admission_ack_invalid$"
            elif fault in {"durable_episode", "durable_result", "execution"}:
                match = "^rsi_python_brs_admission_selected_result_invalid$"
            elif fault.startswith("budget_"):
                match = "^rsi_python_brs_admission_selected_budget_invalid$"
            elif fault == "caller_record":
                match = "^rsi_python_brs_admission_selected_settlement_record_invalid$"
            else:
                match = "^rsi_python_brs_admission_stale$"
            with pytest.raises((RSILearningError, RSIFingerprintError), match=match):
                _settle(value, record, wave, execution)
        assert committed and _rows(value) == committed["rows"]
        assert _evidence_files(value) == files
        assert value.ledger.controller_checkpoint(value.binding.run_id) == committed["durable"]
        assert wave.state == original_state
        assert wave.budget_state == original_state["budget_state"]
        assert (wave.checkpoint_sha256, wave.payload) == (original_head, original_payload)
        assert committed["durable"][1]["budget_state"] == original_state["budget_state"]
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


@pytest.mark.parametrize("fault", ["workspace_and_sidecar", "state_identity"])
def test_owner_settlement_rejects_equal_identity_replacement_after_real_commit(
    tmp_path, monkeypatch, fault,
):
    value = _fixture(tmp_path, monkeypatch)
    with _wave(value) as wave:
        record, execution = _returned(value, wave)
        state_object = wave.state
        original_state = deepcopy(state_object)
        budget_object = wave.budget_state
        original_head, original_payload = wave.checkpoint_sha256, wave.payload
        original_workspace, original_sidecar = wave.workspace, wave.sidecar
        original_save = value.controller._save_flow
        files = _evidence_files(value)
        committed = {}

        def save(*args, **kwargs):
            head = original_save(*args, **kwargs)
            durable = value.ledger.controller_checkpoint(value.binding.run_id)
            assert durable[0] == head != original_head
            assert set(durable[1]["executions"]) == {value.episode_id}
            committed.update(head=head, durable=deepcopy(durable), rows=_rows(value))
            if fault == "workspace_and_sidecar":
                workspace = type(original_workspace)(str(original_workspace))
                sidecar = replace(original_sidecar)
                assert workspace == original_workspace and workspace is not original_workspace
                assert sidecar == original_sidecar and sidecar is not original_sidecar
                value.controller.producer_workspace = wave.workspace = workspace
                value.controller.producer_sidecar = wave.sidecar = sidecar
            else:
                assert fault == "state_identity"
                replacement = deepcopy(wave.state)
                assert replacement == wave.state and replacement is not wave.state
                committed.update(foreign_state=replacement, foreign_state_before=deepcopy(replacement))
                wave.state = replacement
            return head

        with monkeypatch.context() as patch:
            patch.setattr(value.controller, "_save_flow", save)
            with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_selected_identity_invalid$"):
                _settle(value, record, wave, execution)
        assert committed and _rows(value) == committed["rows"]
        assert _evidence_files(value) == files
        assert value.ledger.controller_checkpoint(value.binding.run_id) == committed["durable"]
        assert wave.state is state_object and state_object == original_state
        if fault == "state_identity":
            assert committed["foreign_state"] is not wave.state
            assert committed["foreign_state"] == committed["foreign_state_before"]
        assert wave.budget_state is budget_object and budget_object == original_state["budget_state"]
        assert (wave.checkpoint_sha256, wave.payload) == (original_head, original_payload)
        assert committed["durable"][1]["budget_state"] == original_state["budget_state"]
        _refused(value, wave, lambda: _settle(value, record, wave, execution),
                 match="^rsi_python_brs_admission_selected_settlement_unavailable$")


def _exact_execution_for_payload_guard():
    episode_id, digest = "payload-helper-episode", OTHER
    request = rsi_controller.SolverRequest(
        episode_id, digest, digest, digest, digest, "native",
    )
    check = rsi_controller.VerifierCheck("official_evaluator", "pass", digest)
    verifier = rsi_controller.VerifierDecision(
        episode_id, "pass", digest, "inert-payload-helper", digest, (check,),
        contract_sha256=digest, evaluator_sha256=digest, environment_sha256=digest,
        official_evaluation_receipt_sha256=digest, evidence_sha256=digest,
        candidate_receipt_sha256=digest, execution_receipt_sha256=digest,
    )
    trace = rsi_controller.TraceEvent(0, "observation", "inert-helper", digest)
    episode = rsi_controller.PracticeEpisode(
        episode_id, "payload-helper-run", digest, digest, digest, digest, "native", "completed",
        verifier=verifier, request_sha256=request.digest(), trace_digest=digest,
        candidate_receipt_sha256=digest, execution_receipt_sha256=digest,
        official_evaluation_receipt_sha256=digest, trace_events=(trace,),
    )
    result = rsi_controller.SolverResult(
        episode_id, request.digest(), "completed", candidate_receipt_sha256=digest,
        execution_receipt_sha256=digest, official_evaluation_receipt_sha256=digest,
        trace_digest=digest, solver_score=1.0, terminal_reason="inert-payload-helper",
    )
    execution = rsi_controller.EpisodeExecution(episode, request, result, verifier)
    assert rsi_controller.RSILearningController._python_admission_selected_brs_execution_payload(execution)
    return execution


def test_payload_guard_accepts_failed_execution_without_episode_verifier():
    episode_id, digest = "payload-helper-failed", OTHER
    request = rsi_controller.SolverRequest(
        episode_id, digest, digest, digest, digest, "native",
    )
    check = rsi_controller.VerifierCheck("official_evaluator", "fail", digest)
    verifier = rsi_controller.VerifierDecision(
        episode_id, "fail", digest, "inert-payload-helper", digest, (check,),
        contract_sha256=digest, evaluator_sha256=digest, environment_sha256=digest,
    )
    episode = rsi_controller.PracticeEpisode(
        episode_id, "payload-helper-run", digest, digest, digest, digest, "native", "failed",
        request_sha256=request.digest(), terminal_reason="inert-payload-helper",
    )
    result = rsi_controller.SolverResult(
        episode_id, request.digest(), "failed", digest, digest, digest, digest,
        terminal_reason="inert-payload-helper",
    )
    execution = rsi_controller.EpisodeExecution(episode, request, result, verifier)
    assert rsi_controller.RSILearningController._python_admission_selected_brs_execution_payload(execution)


@pytest.mark.parametrize("target_name", [
    "execution", "episode", "request", "result", "verifier", "check", "trace",
])
@pytest.mark.parametrize("fault", ["dict_subclass", "non_exact_string_key"])
def test_payload_detachment_rejects_attribute_callbacks_without_invoking_them(target_name, fault):
    # Pure exact DTOs establish a valid baseline; no gateway, SQLite, controller
    # lifecycle, or 14-second selected-service fixture is needed by this parser gate.
    execution = _exact_execution_for_payload_guard()
    targets = {
        "execution": execution, "episode": execution.episode, "request": execution.request,
        "result": execution.result, "verifier": execution.verifier,
        "check": execution.verifier.checks[0], "trace": execution.episode.trace_events[0],
    }
    target = targets[target_name]
    calls = []

    class CallbackAttributes(dict):
        def callback(self, *args, **kwargs):
            calls.append("attributes")
            raise AssertionError("worker-owned attribute mapping callback executed")

        __iter__ = callback
        __getitem__ = callback
        __contains__ = callback
        keys = callback
        items = callback
        values = callback

    armed = False

    class CallbackKey(str):
        def __hash__(self):
            if armed:
                calls.append("key_hash")
                raise AssertionError("worker-owned attribute key hash executed")
            return str.__hash__(self)

        def __eq__(self, other):
            if armed:
                calls.append("key_equality")
                raise AssertionError("worker-owned attribute key equality executed")
            return str.__eq__(self, other)

    if fault == "dict_subclass":
        object.__setattr__(target, "__dict__", CallbackAttributes(vars(target)))
        assert type(vars(target)) is CallbackAttributes
    else:
        assert fault == "non_exact_string_key" and type(vars(target)) is dict
        vars(target)[CallbackKey("worker-owned-extra-attribute")] = None
        armed = True
    assert calls == []
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_selected_result_invalid$"):
        rsi_controller.RSILearningController._python_admission_selected_brs_execution_payload(execution)
    assert calls == []


@pytest.mark.parametrize("target_name,field", [("execution", "episode"), ("episode", "verifier")])
def test_payload_detachment_rejects_colliding_keys_before_original_attribute_lookup(target_name, field):
    execution = _exact_execution_for_payload_guard()
    target = execution if target_name == "execution" else execution.episode
    attributes = dict(vars(target))
    original = attributes.pop(field)
    calls = []
    armed = False

    class CollidingAttributeKey(str):
        def __hash__(self):
            return str.__hash__(self)

        def __eq__(self, other):
            if armed:
                calls.append("attribute_equality")
                raise AssertionError("worker-owned colliding attribute key executed")
            return str.__eq__(self, other)

    attributes[CollidingAttributeKey(field)] = original
    object.__setattr__(target, "__dict__", attributes)
    assert type(vars(target)) is dict
    armed = True
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_selected_result_invalid$"):
        rsi_controller.RSILearningController._python_admission_selected_brs_execution_payload(execution)
    assert calls == []


def _worker_callback_value(calls, fault):
    collision = {"primitive_equality": str, "dto_equality": rsi_controller.PracticeEpisode,
                 "container_equality": tuple}.get(fault)

    class CallbackMeta(type):
        def __hash__(cls):
            if fault == "hash":
                calls.append("metaclass_hash")
                raise AssertionError("worker-owned type hash executed")
            return hash(collision)

        def __eq__(cls, other):
            calls.append("metaclass_equality")
            raise AssertionError("worker-owned type equality executed")

    class WorkerValue(metaclass=CallbackMeta):
        pass

    return WorkerValue()


@pytest.mark.parametrize("fault", ["hash", "primitive_equality", "dto_equality", "container_equality"])
@pytest.mark.parametrize("placement", ["dto_field", "tuple_value", "dict_value"])
def test_payload_detachment_rejects_unknown_types_without_metaclass_callbacks(fault, placement):
    execution = _exact_execution_for_payload_guard()
    calls = []
    value = _worker_callback_value(calls, fault)
    if placement == "dto_field":
        object.__setattr__(execution.result, "trace_digest", value)
    else:
        nested = (value,) if placement == "tuple_value" else {"nested": value}
        object.__setattr__(execution.request, "solver_settings", (("worker", nested),))
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_selected_result_invalid$"):
        rsi_controller.RSILearningController._python_admission_selected_brs_execution_payload(execution)
    assert calls == []


@pytest.mark.parametrize("fault", ["hash", "primitive_equality"])
def test_flow_payload_rejects_unknown_nested_type_without_metaclass_callbacks(fault):
    calls = []
    value = _worker_callback_value(calls, fault)
    with pytest.raises(RSILearningError, match="^rsi_python_admission_flow_state_invalid$"):
        rsi_controller.RSILearningController._python_admission_flow_payload({"nested": [value]})
    assert calls == []


def test_wave_identity_gate_rejects_state_subclass_before_calling_get():
    calls = []

    class CallbackState(dict):
        def get(self, *args, **kwargs):
            calls.append("state_get")
            raise AssertionError("worker-owned state get executed")

    # This is a refusal at the first state-container type gate, so no ledger or
    # gateway operation is reachable or replaced with a successful fake.
    controller = object.__new__(rsi_controller.RSILearningController)
    ledger, workspace, sidecar = object(), object(), object()
    wave = rsi_controller._PythonAdmissionBRSWave(
        controller, CallbackState(run_id="guard-run", mode="brs", status="running"),
        "guard-run", ("guard-episode",), ledger, workspace, sidecar,
        0, OTHER, b"{}", object(), {},
    )
    controller.ledger = ledger
    controller.producer_workspace = workspace
    controller.producer_sidecar = sidecar
    controller._python_admission_brs_wave = wave
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_identity_invalid$"):
        controller._python_admission_assert_brs_wave(wave, owner=False)
    assert calls == []


def test_wave_identity_gate_rejects_colliding_state_key_without_equality_callback():
    calls = []
    armed = False

    class CollidingStateKey(str):
        def __hash__(self):
            return str.__hash__(self)

        def __eq__(self, other):
            if armed:
                calls.append("state_key_equality")
                raise AssertionError("worker-owned state key equality executed")
            return str.__eq__(self, other)

    state = {CollidingStateKey("run_id"): "guard-run", "mode": "brs", "status": "running"}
    assert type(state) is dict
    controller = object.__new__(rsi_controller.RSILearningController)
    ledger, workspace, sidecar = object(), object(), object()
    wave = rsi_controller._PythonAdmissionBRSWave(
        controller, state, "guard-run", ("guard-episode",), ledger, workspace, sidecar,
        0, OTHER, b"{}", object(), {},
    )
    controller.ledger = ledger
    controller.producer_workspace = workspace
    controller.producer_sidecar = sidecar
    controller._python_admission_brs_wave = wave
    armed = True
    with pytest.raises(RSILearningError, match="^rsi_python_brs_admission_identity_invalid$"):
        controller._python_admission_assert_brs_wave(wave, owner=False)
    assert calls == []
