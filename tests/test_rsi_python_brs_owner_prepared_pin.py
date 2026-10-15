"""Original owner reference CAS without worker ready, ACK or producer execution."""

from __future__ import annotations

import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from threading import RLock, get_ident

import pytest
import test_rsi_brs_publication_lineage_owner as fixture
import test_rsi_brs_staged_terminal_checkpoint as native_fixture
import test_rsi_python_brs_selected_service as selected
from test_rsi_python_admission import DIGEST

from lunar_evolution import RSILearningError, bundle_evolution, producer_process
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("p")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("owner prepared pin fixture invoked external execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden)
    monkeypatch.setattr(transaction, "run_native_producer_bundle_publication_transaction", forbidden)
    monkeypatch.setattr(staging, "stage_producer_bundle_publication", forbidden)
    monkeypatch.setattr(staging, "commit_producer_bundle_publication", forbidden)


def _pin(value, *, owner=None, anchor=None):
    return value.controller._pin_python_admission_for_original_brs_owner(
        value.owner if owner is None else owner,
        expected_anchor_sha256=value.anchor.anchor_sha256 if anchor is None else anchor,
    )


def _quiet(value):
    assert not value.ready.is_set()
    assert value.messages.empty()
    assert not value.wave.channel._requests
    assert not value.wave.channel._queue
    assert getattr(value.controller._python_admission_flow_local, "active", None) is None
    assert getattr(value.controller._python_admission_brs_local, "active", None) is None
    assert getattr(value.controller._python_admission_brs_local, "selected_service", None) is None


def test_original_owner_pins_exact_reference_then_separate_prepared_evidence(tmp_path, monkeypatch):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        owner, wave = value.owner, value.wave
        owner.checkpoint_before(fixture._before(value))
        before = fixture._capture(value)
        history_before = value.ledger.controller_checkpoint_history(value.binding.run_id)
        pin, calls = value.ledger.pin_python_admission_record, []

        def observed(record, **kwargs):
            assert get_ident() == value.owner_thread != value.worker_thread
            assert value.ledger.controller_lock_held(value.binding.run_id)
            assert getattr(value.ledger._observation_scope, "depth", 0) == 0
            assert kwargs["expected_checkpoint_sha256"] == before[0]
            _quiet(value)
            calls.append(record)
            return pin(record, **kwargs)

        monkeypatch.setattr(value.ledger, "pin_python_admission_record", observed)
        record = _pin(value)
        assert len(calls) == 1 and calls[0].record_sha256 == record
        assert (owner._head, owner._payload, owner._phase) == (before[0], before[1], "before")
        reference_head = wave.checkpoint_sha256
        expected = deepcopy(before[2])
        expected["python_admission_refs"] = deepcopy(wave.state["python_admission_refs"])
        assert wave.state == expected
        assert reference_head != before[0]
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert history[:-1] == history_before and history[-1] == (reference_head, expected)
        assert wave.state["producer_publication_lineage"]["batches"][0]["evidence_pins"] == {}
        _quiet(value)
        evidence_head = owner.acknowledge_prepared(value.journal, record)
        assert evidence_head not in {before[0], reference_head}
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert [head for head, _ in history[-3:]] == [before[0], reference_head, evidence_head]
        assert owner._phase == "prepared-evidence" and not owner._poisoned
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert wave.state["budget_state"] == before[2]["budget_state"]
        assert wave.state["root_snapshot"] == before[2]["root_snapshot"]
        assert value.controller.producer_multi_episode_publication is False
        _quiet(value)


@pytest.mark.parametrize("fault", ["unregistered-clone", "foreign-thread", "registry", "lease", "head", "source",
                                  "memory", "nonce", "budget", "claim-result", "phase"])
def test_original_owner_authority_cannot_be_recreated_or_drift(tmp_path, monkeypatch, fault):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        if fault != "phase":
            value.owner.checkpoint_before(fixture._before(value))
        owner = value.owner
        if fault == "unregistered-clone":
            owner = copy(owner)
        elif fault == "registry":
            value.controller._python_admission_brs_local.lineage_checkpoint_owner = object()
        elif fault == "head":
            value.ledger.write_controller_checkpoint(value.binding.run_id, deepcopy(value.wave.state),
                                                    expected_sha256=value.wave.checkpoint_sha256)
        elif fault == "source":
            value.gateway.fingerprint = "foreign"
        elif fault == "memory":
            object.__setattr__(value.request, "memory_snapshot_sha256", "e" * 64)
        elif fault == "nonce":
            object.__setattr__(value.wave.selected_handoff, "lease_nonce", "Z" * 32)
        elif fault == "budget":
            value.wave.budget_state["planned"]["deadline_unix"] += 1
        elif fault == "claim-result":
            claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
            result = selected.SolverResult(episode_id=value.episode_id, request_sha256=value.request.digest(),
                status="completed", candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
                official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST, terminal_reason="inert")
            value.ledger.publish_native_episode_result(value.request, plan_sha256=value.plan.plan_sha256,
                                                      result=result, expected_claim=claim)
        before = fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with monkeypatch.context() as patch, pytest.raises((RSILearningError, ValueError)):
            if fault == "lease":
                patch.setattr(value.ledger, "controller_lock_held", lambda _run_id: False)
            if fault == "foreign-thread":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(_pin, value).result(timeout=10)
            else:
                _pin(value, owner=owner)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert owner._poisoned
        _quiet(value)


@pytest.mark.parametrize("fault", ["journal-bytes", "handoff-inode", "anchor"])
def test_prepared_reference_requires_original_native_evidence(tmp_path, monkeypatch, fault):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(fixture._before(value))
        if fault == "journal-bytes":
            path = value.batch / "journal.prepared.json"
            path.write_bytes(path.read_bytes() + b"\n")
        elif fault == "handoff-inode":
            path = value.batch / fixture.PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
            raw = path.read_bytes()
            path.rename(path.with_suffix(".inert-original"))
            path.write_bytes(raw)
            path.chmod(0o600)
        before = fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises((RSILearningError, ValueError)):
            _pin(value, anchor="e" * 64 if fault == "anchor" else None)
        fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned
        _quiet(value)


@pytest.mark.parametrize("fault", ["competing-cas", "missing-readback", "wrong-readback", "late-revision",
                                  "journal-inode", "post-source", "post-control", "post-lease"])
def test_unknown_pin_preserves_durable_evidence_and_original_capture(tmp_path, monkeypatch, fault):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(fixture._before(value))
        before = fixture._capture(value)
        pin, read = value.ledger.pin_python_admission_record, value.ledger.controller_checkpoint
        exact = value.controller._python_admission_pin_exact
        durable, calls = [], []

        def observed(record, **kwargs):
            calls.append(True)
            if fault == "competing-cas":
                head = value.ledger.write_controller_checkpoint(value.binding.run_id, deepcopy(value.wave.state),
                                                               expected_sha256=before[0])
                durable.append((head, deepcopy(value.wave.state)))
            result = pin(record, **kwargs)
            durable.append(read(value.binding.run_id))
            return result

        def invalid(run_id):
            if not durable or fault not in {"missing-readback", "wrong-readback"}:
                return read(run_id)
            return None if fault == "missing-readback" else ("e" * 64, durable[-1][1])

        def post_pin(*args, **kwargs):
            result = exact(*args, **kwargs)
            if fault == "late-revision":
                head = value.ledger.write_controller_checkpoint(value.binding.run_id, deepcopy(result[3]),
                                                               expected_sha256=result[1])
                durable.append((head, deepcopy(result[3])))
            elif fault == "journal-inode":
                path = value.batch / "journal.prepared.json"
                raw = path.read_bytes()
                path.rename(path.with_suffix(".inert-original"))
                path.write_bytes(raw)
                path.chmod(0o600)
            elif fault == "post-source":
                value.gateway.fingerprint = "foreign"
            elif fault == "post-control":
                object.__setattr__(value.wave.selected_context, "execution_control_sha256", "e" * 64)
            elif fault == "post-lease":
                monkeypatch.setattr(value.ledger, "controller_lock_held", lambda _run_id: False)
            return result

        monkeypatch.setattr(value.ledger, "pin_python_admission_record", observed)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", invalid)
        monkeypatch.setattr(value.controller, "_python_admission_pin_exact", post_pin)
        with pytest.raises((RSILearningError, ValueError)):
            _pin(value)
        fixture._unchanged(value, before)
        assert calls == [True] and durable
        assert read(value.binding.run_id) == durable[-1]
        assert value.owner._poisoned
        with pytest.raises(RSILearningError):
            _pin(value)
        assert calls == [True]
        _quiet(value)


def test_post_pin_source_hook_can_observe_short_mutex_without_advancing_capture(tmp_path, monkeypatch):
    with fixture._waiting(tmp_path, monkeypatch) as value, ThreadPoolExecutor(max_workers=1) as observer:
        value.owner.checkpoint_before(fixture._before(value))
        before = fixture._capture(value)
        config, pin = value.gateway.rsi_fingerprint_config, value.ledger.pin_python_admission_record
        pinned, calls = [], []

        def observe():
            with value.controller._python_admission_brs_observations():
                return True

        def source():
            assert observer.submit(observe).result(timeout=3)
            if pinned:
                fixture._unchanged(value, before)
                calls.append(get_ident())
            return config()

        def record(*args, **kwargs):
            result = pin(*args, **kwargs)
            pinned.append(True)
            return result

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source)
        monkeypatch.setattr(value.ledger, "pin_python_admission_record", record)
        _pin(value)
        assert calls and set(calls) == {value.owner_thread}
        _quiet(value)


@pytest.mark.parametrize("fault", ["none", "pre-cancel", "pre-nonbool", "post-cancel", "post-timeout",
                                  "post-object", "post-deadline", "post-clock", "post-stage", "post-lock",
                                  "post-callback", "post-cancellation", "post-source-hook-cancel",
                                  "last-active-cancel", "last-active-timeout"])
def test_real_native_control_is_fixed_and_live_across_prepared_cas(tmp_path, monkeypatch, fault):
    now, signal = [0.0], [False]
    control = SolveExecutionControl(30, clock=lambda: now[0], started_at=0)
    original = fixture._setup

    def cancellation():
        return signal[0]

    def setup(root, patch):
        with monkeypatch.context() as nested:
            nested.setattr(fixture, "_setup", original)
            value = native_fixture._native_setup(root, patch)
        object.__setattr__(value.native, "execution_control", control)
        object.__setattr__(value.native, "cancelled", cancellation)
        return value

    monkeypatch.setattr(fixture, "_setup", setup)
    with fixture._waiting(tmp_path, monkeypatch) as value, ThreadPoolExecutor(max_workers=1) as observer:
        value.owner.checkpoint_before(fixture._before(value))
        before = fixture._capture(value)
        exact, config = value.controller._python_admission_pin_exact, value.gateway.rsi_fingerprint_config
        pin = value.ledger.pin_python_admission_record
        durable, hooks, pin_calls, active_calls, at_last_active = [], [], [], [], []

        def observe():
            with value.controller._python_admission_brs_observations():
                return True

        def source():
            if at_last_active:
                if fault == "last-active-cancel":
                    control.cancel()
                else:
                    now[0] = 31
                hooks.append(True)
            if durable and fault == "post-source-hook-cancel":
                assert observer.submit(observe).result(timeout=3)
                control.cancel()
                hooks.append(True)
            return config()

        def post_pin(*args, **kwargs):
            if fault.startswith("last-active-"):
                active = kwargs["active"]
                def last_active():
                    active_calls.append(True)
                    if len(active_calls) == 2:
                        at_last_active.append(True)
                    return active()
                kwargs["active"] = last_active
            result = exact(*args, **kwargs)
            durable.append((result[1], deepcopy(result[3])))
            if fault == "post-cancel":
                control.cancel()
            elif fault == "post-timeout":
                now[0] = 31
            elif fault == "post-object":
                object.__setattr__(value.native, "execution_control", SolveExecutionControl(30, clock=lambda: 0, started_at=0))
            elif fault == "post-deadline":
                control.deadline += 1
            elif fault == "post-clock":
                control._clock = lambda: 0
            elif fault == "post-stage":
                control._observe_stage = lambda _stage: None
            elif fault == "post-lock":
                control._lock = RLock()
            elif fault == "post-callback":
                control.add_cancellation_callback(lambda: False)
            elif fault == "post-cancellation":
                object.__setattr__(value.native, "cancelled", lambda: False)
            return result

        def observed_pin(*args, **kwargs):
            pin_calls.append(True)
            return pin(*args, **kwargs)

        monkeypatch.setattr(value.controller, "_python_admission_pin_exact", post_pin)
        monkeypatch.setattr(value.ledger, "pin_python_admission_record", observed_pin)
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", source)
        if fault == "pre-cancel":
            control.cancel()
        elif fault == "pre-nonbool":
            class BooleanShadow:
                def __bool__(self):
                    raise AssertionError("cancellation result invoked caller boolean callback")
            signal[0] = BooleanShadow()
        if fault == "none":
            _pin(value)
            assert len(durable) == 1 and not value.owner._poisoned
            assert value.native.execution_control is control
        else:
            with pytest.raises(RSILearningError):
                _pin(value)
            fixture._unchanged(value, before)
            assert value.owner._poisoned
            if fault.startswith("post-"):
                assert len(durable) == 1
                assert value.ledger.controller_checkpoint(value.binding.run_id) == durable[0]
            else:
                assert durable == [] and pin_calls == []
                assert value.ledger.controller_checkpoint(value.binding.run_id) == (before[0], before[2])
            if fault == "post-source-hook-cancel":
                assert hooks
            if fault.startswith("last-active-"):
                assert hooks and len(active_calls) == 2
        _quiet(value)
