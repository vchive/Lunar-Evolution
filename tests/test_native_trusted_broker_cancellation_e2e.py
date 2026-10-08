"""Caller cancellation reaches real broker HTTP I/O without publication or replay I/O."""

from __future__ import annotations

import os
import signal
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_http_transport_deadline import clear_proxy_environment
from test_native_trusted_scheduler_e2e import fixture as native_fixture
from test_native_trusted_scheduler_e2e import retained_files
from test_producer_bundle_transaction import _archive_projection

import lunar_evolution.controller_http_transport as http
import lunar_evolution.native_trusted_attempt as native
import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled
from lunar_evolution.producer_bootstrap import TrustedBootstrapSession
from lunar_evolution.producer_broker_ipc import recover_producer_broker_observation
from lunar_evolution.producer_request_transport import HostRequestJournalIdentity

pytestmark = pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform",
)


@contextmanager
def blocked_loopback():
    """Keep response headers blocked until the caller's cleanup has returned."""
    received = threading.Event()
    release = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.path, body))
            received.set()
            # The test releases this only after cancellation has completed. A finite
            # response delay cannot accidentally turn cancellation into ordinary success.
            release.wait()
            try:
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, calls
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def observe_live_boundaries(monkeypatch, received):
    """Delegate every real operation while recording host-accepted start and owned children."""
    native_processes, http_processes, accepted_starts, broker_calls = [], [], [], []
    original_spawn = native.subprocess.Popen
    original_http_spawn = http.Popen
    original_accept = TrustedBootstrapSession.accept_frame
    original_serve = native.serve_producer_broker

    class ObservedNativeProcess(original_spawn):
        def __init__(self, *args, **kwargs):
            self.native_guardian = "--group-pidfd" in args[0]
            super().__init__(*args, **kwargs)
            native_processes.append(self)

    def http_spawn(*args, **kwargs):
        process = original_http_spawn(*args, **kwargs)
        http_processes.append(process)
        return process

    def accept_frame(session, frame):
        original_accept(session, frame)
        if frame.kind == "target_started":
            assert session.state == "target_started" and session.target_start_count == 1
            accepted_starts.append(frame)

    def serve(*args, **kwargs):
        record = {"arguments": kwargs, "observation": None}
        broker_calls.append(record)
        record["observation"] = original_serve(*args, **kwargs)
        return record["observation"]

    # The native stream boundary checks isinstance(Popen); preserve the real class contract.
    monkeypatch.setattr(native.subprocess, "Popen", ObservedNativeProcess)
    monkeypatch.setattr(http, "Popen", http_spawn)
    monkeypatch.setattr(TrustedBootstrapSession, "accept_frame", accept_frame)
    monkeypatch.setattr(native, "serve_producer_broker", serve)

    def cancelled():
        # A target-authored marker alone is insufficient: both host acceptance and
        # an actual server-observed in-flight request precede the cancellation.
        return bool(accepted_starts) and received.is_set()

    return cancelled, native_processes, http_processes, accepted_starts, broker_calls


def assert_children_reaped(native_processes, http_processes):
    bootstraps = [process for process in native_processes if not process.native_guardian]
    guardians = [process for process in native_processes if process.native_guardian]
    assert len(bootstraps) == len(http_processes) == 1
    assert len(guardians) == (1 if sys.platform == "linux" else 0)
    # Linux owns both exact native children. The separately scheduled guardian
    # must be reaped too; excluding it from the bootstrap count is not cleanup.
    for process in (*native_processes, *http_processes):
        assert process.returncode is not None and process.poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)
    worker = http_processes[0]
    assert worker.returncode == -signal.SIGKILL
    assert worker.stdin.closed and worker.stdout.closed
    # The bootstrap owns its own group; the HTTP worker belongs to the caller's group.
    with pytest.raises(ProcessLookupError):
        os.killpg(bootstraps[0].pid, 0)


@pytest.mark.parametrize("acknowledged", [True, False], ids=["confirmed", "acknowledgement_lost"])
def test_active_broker_request_cancellation_is_reaped_and_never_published(
    tmp_path, monkeypatch, acknowledged,
):
    clear_proxy_environment(monkeypatch)
    with blocked_loopback() as (endpoint, received, requests):
        prepared = native_fixture(tmp_path, endpoint)
        before_archive = _archive_projection(prepared.context.workspace)
        cancelled, native_processes, http_processes, accepted_starts, broker_calls = (
            observe_live_boundaries(monkeypatch, received)
        )
        cancellations = []
        original_cancel = http.ControllerHttpHandle.cancel

        def observe_cancel(handle):
            stopped = original_cancel(handle)
            cancellations.append(stopped)
            # The negative case loses the host acknowledgement after physically
            # stopping the real child. Its absence must retain uncertainty.
            return stopped if acknowledged else False

        monkeypatch.setattr(http.ControllerHttpHandle, "cancel", observe_cancel)
        with pytest.raises(SolveExecutionCancelled):
            scheduler.run_native_trusted_producer(
                prepared.context.workspace, **prepared.arguments, cancelled=cancelled,
            )
        assert received.is_set() and len(accepted_starts) == 1
        assert requests == [("/", b"hello")]
        assert cancellations == [True]
        assert_children_reaped(native_processes, http_processes)

    assert _archive_projection(prepared.context.workspace) == before_archive
    assert not (prepared.batch / "execution-receipt.json").exists()
    assert not (prepared.batch / "journal.prepared.json").exists()
    assert not (prepared.batch / "journal.published.json").exists()
    assert len(broker_calls) == 1
    broker = broker_calls[0]["observation"]
    assert broker is not None and broker.complete is False
    assert broker.reason == ("cancelled" if acknowledged else "request_boundary_unknown")
    assert broker.snapshot.admitted_count == 1
    assert broker.snapshot.active_count == (0 if acknowledged else 1)
    assert tuple(event.status for event in broker.snapshot.events) == (
        ("cancelled",) if acknowledged else ()
    )
    args = broker_calls[0]["arguments"]
    identity = HostRequestJournalIdentity(
        launch_id=prepared.intent.launch_id, journal_id=prepared.intent.journal_id,
        run_id=prepared.intent.run_id, parent_task_id=prepared.intent.parent_task_id,
        task_id=prepared.intent.task_id, intent_sha256=prepared.intent.intent_sha256,
        request_timeout_seconds=prepared.intent.request_timeout_seconds,
        max_requests=prepared.intent.max_requests, wall_deadline_ns=args["deadline_ns"],
    )
    before_recovery = retained_files(prepared.context.workspace)

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only cancellation recovery must not launch or contact a provider")

    monkeypatch.setattr(native.subprocess, "Popen", forbidden)
    monkeypatch.setattr(http.ControllerHttpTransport, "start", forbidden)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", forbidden)
    for _ in range(2):
        terminal = native.recover_native_trusted_attempt(
            prepared.context.workspace, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
        # Process-only cancellation proves native cleanup. It never upgrades an
        # unconfirmed broker request into execution/output/publication authority.
        assert terminal["process_status"] == "cancelled"
        assert terminal["cleanup_status"] in {"cleaned", "already_exited"}
        lifecycle = native.audit_native_trusted_lifecycle(
            prepared.context.workspace, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
        assert lifecycle["status"] == "process_only"
        assert lifecycle["publication_eligible"] is False
        recovered = recover_producer_broker_observation(
            broker.journal_path, identity=identity, deadline_ns=args["deadline_ns"],
            expected_journal_sha256=broker.journal_sha256,
            expected_journal_bytes=broker.journal_bytes,
            expected_journal_file_identity=broker.journal_file_identity,
        )
        assert recovered.snapshot == broker.snapshot
        assert recovered.complete is acknowledged
        with pytest.raises(scheduler.NativeTrustedSchedulerError, match="recovery_receipt_invalid"):
            scheduler.recover_native_trusted_producer(
                prepared.context.workspace, **prepared.recovery,
            )
        assert retained_files(prepared.context.workspace) == before_recovery
    assert requests == [("/", b"hello")]
