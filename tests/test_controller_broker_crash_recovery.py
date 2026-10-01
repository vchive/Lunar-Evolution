"""Controller-only hard death and read-only journal replay use local fixtures only."""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import controller_http_transport, http_transport
from lunar_evolution.producer_broker_ipc import (
    ProducerBrokerIpcError,
    recover_producer_broker_observation,
)
from lunar_evolution.producer_request_transport import HostRequestJournalIdentity

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX worker lifeline")

_BODY = b"crash-fixture"
_CONTROLLER = r'''
import json
import os
import signal
import sys
from pathlib import Path
from lunar_evolution import controller_http_transport as transport, http_transport
from lunar_evolution.controller_request_broker import ControllerOwnedRequestBroker
from lunar_evolution.producer_request_transport import (
    HostRequestJournal, HostRequestJournalIdentity, HostRequestLedger,
)

identity = HostRequestJournalIdentity(**json.loads(sys.argv[1]))
path, endpoint, phase = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
http_transport._configuration = lambda: {
    "proxies": {}, "proxy_source": "environment", "trust": {},
}
original_spawn = transport.Popen
workers = []

def spawn(*args, **kwargs):
    process = original_spawn(*args, **kwargs)
    workers.append((process, kwargs))
    return process

transport.Popen = spawn

class ObservedTransport(transport.ControllerHttpTransport):
    def start(self, admission, payload):
        handle = super().start(admission, payload)
        process, options = workers[0]
        print(json.dumps({
            "worker_pid": process.pid,
            "worker_pgid": os.getpgid(process.pid),
            "worker_count": len(workers),
            "pass_fds": list(options["pass_fds"]),
            "lifeline_writer": handle._lifeline,
            "empty_environment": options["env"] == {},
            "close_fds": options["close_fds"],
            "admission_sequence": admission.sequence,
            "admission_started_ns": admission.started_ns,
            "admission_deadline_ns": admission.deadline_ns,
        }), flush=True)
        if phase == "before_outbound_io":
            # Fault injection only: pause before the handle sends request IPC.
            # Killing the controller must release the worker's lifeline reader.
            signal.pause()
        return handle

with HostRequestJournal.create(path, identity) as journal:
    ledger = HostRequestLedger(
        request_timeout_seconds=identity.request_timeout_seconds,
        max_requests=identity.max_requests, journal=journal,
    )
    ControllerOwnedRequestBroker(ledger, ObservedTransport()).execute(
        "request-001", transport.ControllerHttpRequest(endpoint, {}, b"crash-fixture"),
    )
'''


@contextmanager
def _blocked_loopback():
    requests = []
    received = threading.Event()
    disconnected = threading.Event()
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(body)
            received.set()
            # Withhold response headers. Peer EOF/reset proves the local socket
            # closed even though its original request deadline has not elapsed.
            self.connection.settimeout(0.05)
            while not stop.is_set():
                try:
                    data = self.connection.recv(1)
                except TimeoutError:
                    continue
                except OSError:
                    disconnected.set()
                    return
                if not data:
                    disconnected.set()
                    return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield SimpleNamespace(
            endpoint=f"http://127.0.0.1:{server.server_port}", requests=requests,
            received=received, disconnected=disconnected,
        )
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def _worker_state(pid):
    observed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True, text=True, timeout=2, check=False,
    )
    assert observed.returncode in {0, 1}
    return observed.stdout.strip()


def _wait_for_worker_exit(pid):
    deadline = time.monotonic() + 3
    while True:
        state = _worker_state(pid)
        if not state or state.startswith("Z"):
            return state
        assert time.monotonic() < deadline, "worker must stop before fixture cleanup"
        time.sleep(0.01)


def _inventory(home):
    return {
        path.relative_to(home).as_posix(): (
            path.read_bytes(), path.stat().st_dev, path.stat().st_ino, path.stat().st_mtime_ns,
        )
        for path in home.rglob("*") if path.is_file()
    }


@contextmanager
def _crashed_broker(tmp_path, phase):
    home = tmp_path / "controller-journal"
    home.mkdir(mode=0o700)
    path = home / "requests"
    identity = HostRequestJournalIdentity(
        launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", intent_sha256="a" * 64,
        request_timeout_seconds=20, max_requests=1,
        wall_deadline_ns=time.monotonic_ns() + 30_000_000_000,
    )
    source = str(Path(http_transport.__file__).resolve().parents[1])
    with _blocked_loopback() as peer:
        controller = subprocess.Popen(
            [sys.executable, "-B", "-c", _CONTROLLER, json.dumps(identity.to_dict()),
             str(path), peer.endpoint, phase],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={"PYTHONPATH": source}, start_new_session=True,
        )
        try:
            assert select.select([controller.stdout], [], [], 5)[0], "controller startup"
            raw_metadata = controller.stdout.readline(4096)
            assert raw_metadata.endswith(b"\n") and len(raw_metadata) < 4096
            metadata = json.loads(raw_metadata)
            assert metadata["worker_count"] == 1
            assert metadata["worker_pgid"] == controller.pid
            assert metadata["empty_environment"] is True and metadata["close_fds"] is True
            assert len(metadata["pass_fds"]) == 1
            assert metadata["lifeline_writer"] not in metadata["pass_fds"]
            if phase == "waiting_for_headers":
                assert peer.received.wait(5), "fixture must observe active POST before death"
                assert peer.requests == [_BODY]
            else:
                assert phase == "before_outbound_io" and peer.requests == []
            raw = path.read_bytes()
            file_identity = (path.stat().st_dev, path.stat().st_ino)
            records = [json.loads(line) for line in raw.splitlines()]
            assert [record["kind"] for record in records] == ["header", "admitted"]
            assert records[0]["identity"] == identity.to_dict()
            admission = records[1]
            assert admission["sequence"] == metadata["admission_sequence"] == 1
            assert admission["request_id"] == "request-001"
            assert admission["started_ns"] == metadata["admission_started_ns"]
            assert admission["deadline_ns"] == metadata["admission_deadline_ns"] == min(
                admission["started_ns"] + identity.request_timeout_seconds * 1_000_000_000,
                identity.wall_deadline_ns,
            )
            assert time.monotonic_ns() < admission["deadline_ns"]
            controller.kill()  # Only this PID; no process-group signal grants the stop proof.
            assert controller.wait(timeout=3) == -signal.SIGKILL
            if phase == "waiting_for_headers":
                assert peer.disconnected.wait(3), "lifeline must close the blocked HTTP socket"
            state = _wait_for_worker_exit(metadata["worker_pid"])
            assert not state or state.startswith("Z")
            assert time.monotonic_ns() < admission["deadline_ns"]
            assert path.read_bytes() == raw
            assert (path.stat().st_dev, path.stat().st_ino) == file_identity
            assert len(peer.requests) == (1 if phase == "waiting_for_headers" else 0)
            yield SimpleNamespace(
                home=home, path=path, identity=identity, raw=raw, file_identity=file_identity,
                journal_sha256=hashlib.sha256(raw).hexdigest(), admission=admission, peer=peer,
            )
        finally:
            if controller.poll() is None:
                controller.kill()
                controller.wait(timeout=3)
            # This test owns the isolated group. Cleanup is outside both the stop
            # assertions and recovery; exited orphans need not be reaped by this caller.
            try:
                os.killpg(controller.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            controller.stdout.close()


@contextmanager
def _read_only_recovery(monkeypatch):
    original_open = os.open

    def forbidden(*_args, **_kwargs):
        pytest.fail("crash recovery must not start I/O, spawn, or signal")

    def readonly_open(path, flags, *_args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_WRONLY | os.O_RDWR)
        return original_open(path, flags, *_args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(controller_http_transport.ControllerHttpTransport, "start", forbidden)
        guard.setattr(controller_http_transport, "Popen", forbidden)
        guard.setattr(http_transport, "Popen", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(os, "kill", forbidden)
        guard.setattr(os, "killpg", forbidden)
        guard.setattr(os, "open", readonly_open)
        yield


def _recovery_arguments(crashed):
    return {
        "identity": crashed.identity,
        # This bounds read-only replay only; the persisted request deadline is unchanged.
        "deadline_ns": time.monotonic_ns() + 3_000_000_000,
        "expected_journal_sha256": crashed.journal_sha256,
        "expected_journal_bytes": len(crashed.raw),
        "expected_journal_file_identity": crashed.file_identity,
    }


@pytest.mark.parametrize("phase", ["before_outbound_io", "waiting_for_headers"])
def test_controller_death_stops_worker_but_recovery_retains_active_unknown(tmp_path, monkeypatch, phase):
    with _crashed_broker(tmp_path, phase) as crashed:
        before = _inventory(crashed.home)
        with _read_only_recovery(monkeypatch):
            recovered = recover_producer_broker_observation(
                crashed.path, **_recovery_arguments(crashed),
            )
        assert not recovered.complete and recovered.reason == "recovery_required"
        assert recovered.snapshot.admitted_count == 1 and recovered.snapshot.active_count == 1
        assert recovered.snapshot.events == () and not recovered.snapshot.within_broker_limits
        assert recovered.snapshot.coverage == "brokered_requests_only"
        assert recovered.journal_identity == crashed.identity
        assert recovered.journal_file_identity == crashed.file_identity
        assert recovered.journal_sha256 == crashed.journal_sha256
        assert recovered.journal_bytes == len(crashed.raw)
        assert _inventory(crashed.home) == before
        assert len(crashed.peer.requests) == (1 if phase == "waiting_for_headers" else 0)
        records = [json.loads(line) for line in crashed.path.read_bytes().splitlines()]
        assert records[1] == crashed.admission


@pytest.mark.parametrize("binding", ["hash", "bytes", "budget", "same_content_replacement"])
def test_controller_crash_recovery_rejects_changed_binding_without_side_effects(
    tmp_path, monkeypatch, binding,
):
    with _crashed_broker(tmp_path, "waiting_for_headers") as crashed:
        arguments = _recovery_arguments(crashed)
        if binding == "hash":
            arguments["expected_journal_sha256"] = "0" * 64
        elif binding == "bytes":
            arguments["expected_journal_bytes"] = len(crashed.raw) - 1
        elif binding == "budget":
            arguments["identity"] = replace(crashed.identity, max_requests=2)
        else:
            replacement = crashed.home / "replacement"
            replacement.write_bytes(crashed.raw)
            replacement.chmod(0o600)
            os.replace(replacement, crashed.path)
            assert (crashed.path.stat().st_dev, crashed.path.stat().st_ino) != crashed.file_identity
        before = _inventory(crashed.home)
        with _read_only_recovery(monkeypatch), pytest.raises(ProducerBrokerIpcError) as caught:
            recover_producer_broker_observation(crashed.path, **arguments)
        assert caught.value.code == (
            "producer_broker_recovery_journal_mismatch" if binding in {"hash", "bytes"}
            else "producer_broker_recovery_journal_invalid"
        )
        assert _inventory(crashed.home) == before and crashed.peer.requests == [_BODY]
