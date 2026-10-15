"""BRS workers cannot turn prepared admission into publication authority."""

from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from test_rsi_python_admission import _files, _rows
from test_rsi_python_admission_flow import _forged_checkpoint_append
from test_rsi_python_admission_owner import (
    _owner,
    _state,
    _unregistered_publication,
    no_actual_worker_or_evaluator,  # noqa: F401 -- imported autouse fixture
)
from test_rsi_python_brs_selected_service import _ack_and_result, _fixture
from test_rsi_python_brs_selected_service import _wave as _selected_wave

import lunar_evolution
from lunar_evolution import rsi_python_publication as publication
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionControl,
)
from lunar_evolution.rsi_store import RSILedger

ERROR = "rsi_python_publication_brs_worker_publication_forbidden"


def _call(value, *, entry="named", admission_plan=None, **kwargs):
    arguments = (
        value.controller, value.binding.run_id, value.episode_id,
        getattr(value, "strategy", object()), getattr(value, "drafts", ()),
        getattr(value, "admission_plan", object()) if admission_plan is None else admission_plan,
    )
    if entry == "generic":
        return publication.run_rsi_python_bundle_publication(
            *arguments, expected_admission_record_sha256="1" * 64, **kwargs,
        )
    function = (
        publication.run_rsi_python_bundle_publication_for_active_flow if entry == "drs"
        else publication.run_rsi_python_bundle_publication_for_active_brs_worker
    )
    return function(
        *arguments, native_plan=value.plan, prepared_journal=value.journal,
        expected_anchor_sha256=value.anchor.anchor_sha256, **kwargs,
    )


@contextmanager
def _wave(value):
    # Only the dispatch mode changes in this inert fixture. The original request,
    # producer proof, episode, native claim and deadlines remain independently pinned.
    _forged_checkpoint_append(value, lambda state: state.update(mode="brs"))
    state = _state(value)
    with (
        value.ledger.controller_lock(value.binding.run_id),
        value.controller._python_admission_brs_wave_scope(state, (value.episode_id,)) as wave,
    ):
        yield wave, state


def _drive(value, monkeypatch, operation, *, handler=None):
    """Use a real dispatch token/channel; the existing running fixture skips runner launch."""
    def dispatched(state, episode_id):
        with value.controller._python_admission_brs_worker_scope(state, episode_id):
            return operation()

    monkeypatch.setattr(value.controller, "_execute_intent", dispatched)
    with _wave(value) as (wave, state):
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(value.controller._execute_brs_intent, wave, state, value.episode_id)
            # The real local transaction rechecks original files at each boundary.
            # Keep a bounded fixture watchdog which accommodates CI filesystem work;
            # this does not replace or extend the retained execution deadline.
            deadline = time.monotonic() + 60
            while not future.done():
                if time.monotonic() >= deadline:
                    pytest.fail("BRS publication owner/worker did not make progress")
                wave.channel.service(
                    handler or (lambda ready: value.controller._python_admission_service_brs_ready(wave, ready)),
                    timeout=0.05,
                    observation_scope=lambda: value.controller._python_admission_brs_service_observations(wave),
                )
            return future.result()
        finally:
            # A failed owner must wake the waiting worker before executor shutdown.
            wave.channel.close()
            pool.shutdown(wait=True)


def _forbid_mutation_boundaries(monkeypatch, value, calls):
    def forbidden(*args, **kwargs):
        calls.append("unexpected-boundary")
        pytest.fail("BRS worker publication reached parsing, ready, transaction or evaluation")

    for name in ("_plan_snapshot", "_capture_admission", "run_native_producer_bundle_publication_transaction"):
        monkeypatch.setattr(publication, name, forbidden)
    monkeypatch.setattr(value.controller, "_request_python_admission_for_brs_worker", forbidden)
    monkeypatch.setattr(value.controller, "_python_admission_inputs", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.mark.parametrize("scope", ["direct", "drs-owner", "unscoped-worker"])
def test_named_worker_symbol_refuses_without_observing_inputs_or_mutating(tmp_path, monkeypatch, scope):
    value = _unregistered_publication(tmp_path)
    before = _rows(value), _files(value), value.gateway.calls
    calls = []
    _forbid_mutation_boundaries(monkeypatch, value, calls)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        if scope == "drs-owner":
            with _owner(value):
                _call(value)
        elif scope == "unscoped-worker":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_call, value).result(timeout=5)
        else:
            _call(value)
    assert caught.value.code == ERROR and calls == []
    assert (_rows(value), _files(value), value.gateway.calls) == before


@pytest.mark.parametrize("entry", ["named", "generic", "drs"])
@pytest.mark.parametrize("after_ack", [False, True])
def test_actual_selected_worker_cannot_publish_or_bypass_through_other_mutation_facades(
    tmp_path, monkeypatch, entry, after_ack,
):
    value = _fixture(tmp_path, monkeypatch)
    observations = []

    def operation(request):
        result = _ack_and_result(value, request) if after_ack else None
        before = _rows(value), _files(value), value.gateway.calls
        calls = []
        with monkeypatch.context() as refusal_patch:
            _forbid_mutation_boundaries(refusal_patch, value, calls)
            with pytest.raises(publication.RSIPythonPublicationError) as caught:
                _call(value, entry=entry)
            assert caught.value.code == ERROR and calls == []
            assert (_rows(value), _files(value), value.gateway.calls) == before
        observations.append(after_ack)
        return _ack_and_result(value, request) if result is None else result

    value.operation = operation
    with _selected_wave(value) as wave:
        execution = value.controller._python_admission_run_selected_brs_intent(wave)
        assert wave.selected_return is not None
        assert execution.episode.status == execution.result.status == "completed"
        assert wave.channel._completed_selected_episodes == {value.episode_id}
        assert set(wave.state["python_admission_refs"]) == {value.episode_id}
    assert observations == [after_ack]
    assert value.gateway.calls == 1
    assert value.ledger.get_episode(value.sibling_id) is None
    assert not (value.workspace / "evolution" / "producer-publication.json").exists()


@pytest.mark.parametrize("entry", ["named", "generic", "drs"])
@pytest.mark.parametrize("malicious", ["serializer", "attribute-mapping"])
def test_active_worker_refusal_precedes_malicious_admission_plan_callbacks(
    tmp_path, monkeypatch, entry, malicious,
):
    value = _fixture(tmp_path, monkeypatch)
    callbacks = []

    class MaliciousPlan:
        def to_dict(self):
            callbacks.append("serializer")
            raise AssertionError("worker plan serializer ran")

        def __getattribute__(self, name):
            if malicious == "attribute-mapping":
                callbacks.append("attribute-mapping")
                raise AssertionError("worker plan attribute callback ran")
            return object.__getattribute__(self, name)

    def operation(request):
        before = _rows(value), _files(value)
        with pytest.raises(publication.RSIPythonPublicationError) as caught:
            _call(value, entry=entry, admission_plan=MaliciousPlan())
        assert caught.value.code == ERROR and callbacks == []
        assert (_rows(value), _files(value)) == before
        return _ack_and_result(value, request)

    value.operation = operation
    with _selected_wave(value) as wave:
        value.controller._python_admission_run_selected_brs_intent(wave)
    assert value.gateway.calls == 1 and callbacks == []


@pytest.mark.parametrize("stop", ["cancelled", "expired"])
def test_named_refusal_does_not_sample_control_or_caller_guards(tmp_path, monkeypatch, stop):
    value = _unregistered_publication(tmp_path)
    clock = {"now": 100.0}
    control = SolveExecutionControl(30, clock=lambda: clock["now"])
    if stop == "cancelled":
        control.cancel()
    else:
        clock["now"] = control.deadline
    calls = []

    def guard(stage):
        calls.append(stage)
        raise AssertionError("worker caller guard ran")

    def check(stage):
        calls.append(stage)
        raise AssertionError("worker control callback ran")

    monkeypatch.setattr(control, "check", check)
    before = _rows(value), _files(value)
    with pytest.raises(publication.RSIPythonPublicationError) as caught:
        _call(value, execution_control=control, continuation_guard=guard)
    assert caught.value.code == ERROR and calls == []
    assert (_rows(value), _files(value)) == before


def test_named_worker_import_symbol_is_retained():
    name = "run_rsi_python_bundle_publication_for_active_brs_worker"
    assert name in publication.__all__
    assert getattr(lunar_evolution, name) is getattr(publication, name)


@pytest.mark.parametrize("failure", ["deadline", "timeout", "os-error"])
def test_owner_lock_releases_without_reclassifying_body_timeouts_or_os_errors(tmp_path, failure):
    ledger = RSILedger(tmp_path / "owner.sqlite3")
    if failure == "deadline":
        error = SolveExecutionBudgetExceeded("brs_wait", started_at=1, deadline=2, observed_at=2)
    elif failure == "timeout":
        error = TimeoutError("inert-original-timeout")
    else:
        error = OSError("inert-provider-error")
    with pytest.raises(type(error)) as caught, ledger.controller_lock("run-1"):
        assert ledger.controller_lock_held("run-1")
        raise error
    assert caught.value is error
    assert not ledger.controller_lock_held("run-1")
    with ledger.controller_lock("run-1"):
        assert ledger.controller_lock_held("run-1")
