"""Real local channels/wrapper/HMAC/SQLite; no SSH host or evaluator."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from external_worker_fixtures import (
    PLAN,
    SECRET,
    assert_no_native_authority,
    lines,
    worker_harness,
)

from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.external_worker_transport import (
    SSHWorkerConfig,
    SSHWorkerTransport,
    WorkerTransportError,
    load_ssh_worker_config,
)
from lunar_evolution.external_worker_wrapper import WorkerWrapperError, worker_json
from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_learning import RSILearningError


def dispatch(h, control=None):
    with h.ledger.controller_lock("run-local"):
        return h.transport.dispatch(h.request, plan_sha256=PLAN,
            expected_controller_checkpoint_sha256=h.checkpoint,
            control=control or SolveExecutionControl(20))


def reconcile(h):
    with h.ledger.controller_lock("run-local"):
        return h.transport.reconcile(h.request, plan_sha256=PLAN,
            expected_controller_checkpoint_sha256=h.checkpoint, control=SolveExecutionControl(20))


def test_fixed_local_ssh_channel_executes_real_wrapper_once_and_authenticates(tmp_path):
    h = worker_harness(tmp_path)
    before = h.transport.inspect(h.request.episode_id)
    assert before["transport"]["status"] == "not_started" and not h.ssh_marker.exists()
    result = dispatch(h)
    assert result["assignment"]["status"] == "receipt_authenticated"
    assert result["transport"]["status"] == "receipt_authenticated"
    assert len(lines(h.marker)) == len(lines(h.ssh_marker)) == 1
    call = lines(h.ssh_marker)[0]
    assert call["argv"][-2] == "fixture-host"
    assert "-oStrictHostKeyChecking=yes" in call["argv"]
    assert "-oForwardAgent=no" in call["argv"]
    assert SECRET.decode() not in repr(call) + repr(lines(h.marker)) + repr(result) + repr(h.config)
    with pytest.raises(WorkerTransportError, match="once_only"):
        dispatch(h)
    assert len(lines(h.marker)) == len(lines(h.ssh_marker)) == 1
    assert_no_native_authority(h, result)


def test_lost_sealed_response_reconciles_original_unknown_without_reexecution(tmp_path):
    h = worker_harness(tmp_path, drop=True)
    result = dispatch(h)
    assert result["assignment"]["status"] == "unknown"
    original = result["assignment"]["settlement"]
    assert len(lines(h.marker)) == 1
    recovered = reconcile(h)
    assert recovered["assignment"]["status"] == "receipt_authenticated_after_unknown"
    assert recovered["assignment"]["settlement"] == original
    assert recovered["assignment"]["reconciliation"]["outcome"] == "receipt_authenticated"
    assert [json.loads(x["wire"])["action"] for x in lines(h.ssh_marker)] == ["run", "inspect"]
    assert len(lines(h.marker)) == 1
    assert reconcile(h) == recovered
    assert len(lines(h.ssh_marker)) == 2
    with pytest.raises(WorkerTransportError, match="once_only"):
        dispatch(h)
    assert_no_native_authority(h, recovered)


def test_controller_crash_after_transport_intent_never_repeats_run(tmp_path, monkeypatch):
    from lunar_evolution import external_worker_transport as module

    h = worker_harness(tmp_path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(module, "run_worker_channel", interrupted)
        with pytest.raises(KeyboardInterrupt):
            dispatch(h)
    assert h.transport.inspect(h.request.episode_id)["transport"]["status"] == "recovery_required"
    with pytest.raises(WorkerTransportError, match="once_only"):
        dispatch(h)
    result = reconcile(h)
    assert result["assignment"]["status"] == "unknown"
    assert not h.marker.exists()
    assert len(lines(h.ssh_marker)) == 1
    assert json.loads(lines(h.ssh_marker)[0]["wire"])["action"] == "inspect"
    assert_no_native_authority(h, result)


def test_expired_cancelled_or_foreign_config_does_not_admit_channel(tmp_path):
    h = worker_harness(tmp_path)
    control = SolveExecutionControl(20)
    control.cancel()
    with pytest.raises(SolveExecutionCancelled):
        dispatch(h, control)
    assert not h.ssh_marker.exists()
    assert h.transport.inspect(h.request.episode_id)["transport"]["status"] == "not_started"
    with pytest.raises(SolveExecutionBudgetExceeded):
        dispatch(h, SolveExecutionControl(1, started_at=0, clock=lambda: 2))
    assert not h.ssh_marker.exists()
    h.transport = SSHWorkerTransport(h.book, replace(h.config, worker_id="foreign"))
    with pytest.raises(WorkerTransportError, match="assignment_drift"):
        dispatch(h)
    assert not h.ssh_marker.exists()


@pytest.mark.parametrize("host", ["-oProxyCommand=bad", "host;bad", "host bad", "host\nbad", ""])
def test_untrusted_ssh_host_fragments_refused(host):
    with pytest.raises(WorkerTransportError):
        SSHWorkerConfig("/usr/bin/ssh", host, ("/usr/bin/python3",), "worker")


def test_public_ssh_config_exact_roundtrip_and_drift_gate(tmp_path):
    h = worker_harness(tmp_path)
    config = tmp_path / "ssh.json"
    config.write_bytes(worker_json(h.config.to_dict()))
    config.chmod(0o600)
    assert load_ssh_worker_config(config) == h.config
    dispatch(h)
    changed = SSHWorkerTransport(h.book, replace(h.config, host="other-host"))
    with pytest.raises(WorkerTransportError, match="binding_drift"):
        changed.inspect(h.request.episode_id)
    assert DurableCallbackJournal.digest(h.config.to_dict()) == h.transport.inspect(h.request.episode_id)["transport"]["config_sha256"]


def test_simultaneous_controller_dispatches_only_one_original_channel(tmp_path):
    h = worker_harness(tmp_path)
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        try:
            return dispatch(h)["assignment"]["status"]
        except (RSILearningError, WorkerTransportError):
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]
    assert sorted(outcomes) == ["receipt_authenticated", "refused"]
    assert len(lines(h.marker)) == len(lines(h.ssh_marker)) == 1
    assert_no_native_authority(h)


def test_read_only_inspection_does_not_need_original_controller_lock(tmp_path):
    h = worker_harness(tmp_path)
    dispatch(h)
    before = lines(h.ssh_marker)
    assert h.transport.inspect(h.request.episode_id)["assignment"]["status"] == "receipt_authenticated"
    assert lines(h.ssh_marker) == before


def test_forged_remote_receipt_cannot_consume_original_assignment(tmp_path):
    h = worker_harness(tmp_path)
    h.key_file.write_bytes(b"different-worker-key-material-1234567890")
    result = dispatch(h)
    assert result["assignment"]["status"] == "unknown"
    assert len(lines(h.marker)) == 1
    assert reconcile(h)["assignment"]["status"] == "unknown"
    assert len(lines(h.marker)) == 1
    assert_no_native_authority(h, result)


@pytest.mark.parametrize("budget", [{}, {"wall_timeout_seconds": 10}, {"deadline_unix": 10000000000},
                                    {"wall_timeout_seconds": True, "deadline_unix": 10000000000}])
def test_relative_or_episode_only_budget_cannot_create_new_work_deadline(tmp_path, budget):
    h = worker_harness(tmp_path, budget=budget)
    with pytest.raises(WorkerWrapperError, match="original_budget_required"):
        dispatch(h, SolveExecutionControl(30))
    assert h.transport.inspect(h.request.episode_id)["transport"]["status"] == "not_started"
    assert not h.marker.exists() and not h.ssh_marker.exists()


def test_expired_original_request_deadline_refuses_new_channel_budget(tmp_path):
    h = worker_harness(tmp_path, budget={"wall_timeout_seconds": 10, "deadline_unix": 1.0})
    with pytest.raises(WorkerTransportError, match="original_deadline_expired"):
        dispatch(h, SolveExecutionControl(30))
    assert h.transport.inspect(h.request.episode_id)["transport"]["status"] == "not_started"
    assert not h.marker.exists() and not h.ssh_marker.exists()


def test_new_channel_control_cannot_extend_original_wall_or_absolute_deadline(tmp_path, monkeypatch):
    from lunar_evolution import external_worker_transport as module
    from lunar_evolution.external_worker_io import WorkerChannelOutput

    original_deadline = time.time() + 10
    h = worker_harness(tmp_path, budget={"wall_timeout_seconds": 0.25,
                                       "deadline_unix": original_deadline})
    observed = {}

    def channel(_argv, raw, *, control, **_kwargs):
        observed.update(wire=json.loads(raw), remaining=control.remaining())
        return WorkerChannelOutput(8, b"")

    monkeypatch.setattr(module, "run_worker_channel", channel)
    assert dispatch(h, SolveExecutionControl(30))["assignment"]["status"] == "unknown"
    assert 0 < observed["wire"]["timeout_seconds"] <= 0.25
    assert 0 < observed["remaining"] <= 0.25
    assert observed["wire"]["deadline_unix"] <= original_deadline
    assert not h.marker.exists() and not h.ssh_marker.exists()
