"""Absolute HTTP deadlines with local processes and loopback fixtures only."""

import base64
import importlib
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_model_failure_evidence import SECRET, observer_payload

import lunar_evolution.runtime as rt


def transport():
    return importlib.import_module("lunar_evolution.http_transport")


@contextmanager
def local_http(mode="success", status=200, disconnected=None):
    requests = []
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.path, body, dict(self.headers)))
            if mode == "headers":
                stop.wait(3)
            raw = json.dumps({"choices": [{"message": {"content": "done"}}]}).encode()
            if mode == "error":
                raw = SECRET.encode() * 100
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if mode in {"body", "error"}:
                    for index in range(0, len(raw), 4):
                        if stop.wait(0.06):
                            return
                        self.wfile.write(raw[index:index + 4])
                        self.wfile.flush()
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                if disconnected is not None:
                    disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("mode,status,phase", [
    ("headers", 200, "open_response"), ("body", 200, "read_response_body"),
    ("error", 503, "read_http_error_body"),
])
def test_absolute_deadline_from_non_main_thread(tmp_path, mode, status, phase):
    with local_http(mode, status) as (endpoint, calls), ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        future = pool.submit(rt.OpenAICompatibleRuntime(endpoint, "fixture", SECRET).complete, [], (), 0.3)
        with pytest.raises(rt.ModelRequestFailure) as caught:
            future.result(timeout=2)
        elapsed = time.monotonic() - start
    assert elapsed < 0.8 and len(calls) <= 1
    payload = observer_payload(tmp_path, caught.value)
    assert payload["request_observation"]["phase"] == phase
    assert payload["model_failure"]["reason"] == ("http_error" if status == 503 else "transport_timeout")
    assert payload["code"] == ("model_http_failed" if status == 503 else "timeout")
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("timeout", [True, False, 0, -1, float("nan"), float("inf"), 86401, 10**400])
def test_invalid_timeout_rejected_before_process_or_network(monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid timeout must not dispatch")

    monkeypatch.setattr(rt, "urlopen", forbidden)
    with pytest.raises(ValueError):
        rt.OpenAICompatibleRuntime("http://local.invalid", "fixture").complete([], timeout=timeout)


def spy_processes(monkeypatch):
    module = transport()
    original = module.Popen
    processes, parameters = [], []

    def spawn(*args, **kwargs):
        parameters.append((args, kwargs))
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(module, "Popen", spawn)
    return processes, parameters


def assert_closed(processes):
    assert processes
    for process in processes:
        assert process.poll() is not None
        assert process.stdin.closed and process.stdout.closed


def test_finite_success_preserves_wire_and_scrubs_child_environment(monkeypatch):
    processes, parameters = spy_processes(monkeypatch)
    for key in ("LUNAR_EVOLUTION_API_KEY", "SSLKEYLOGFILE", "PYTHONPATH", "UNRELATED_SECRET"):
        monkeypatch.setenv(key, SECRET)
    with local_http() as (endpoint, calls):
        result = rt.OpenAICompatibleRuntime(endpoint, "fixture", SECRET).complete(
            [{"role": "user", "content": "hello"}], timeout=2,
        )
    assert result == rt.ModelTurn("done") and len(calls) == 1
    assert json.loads(calls[0][1]) == {"model": "fixture", "messages": [{"role": "user", "content": "hello"}], "stream": False}
    assert calls[0][2]["Authorization"] == "Bearer " + SECRET
    args, kwargs = parameters[0]
    assert SECRET not in repr(args) and endpoint not in repr(args)
    assert kwargs["env"] == {} and kwargs["close_fds"] is True
    assert not kwargs.get("start_new_session", False) and "preexec_fn" not in kwargs
    assert len(kwargs["pass_fds"]) == 1
    assert_closed(processes)


def test_none_uses_direct_transport_without_spawn(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("None must not spawn")

    monkeypatch.setattr(transport(), "Popen", forbidden)
    with local_http() as (endpoint, calls):
        assert rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=None) == rt.ModelTurn("done")
    assert len(calls) == 1


def test_dns_stall_is_killed_and_reaped(monkeypatch, tmp_path):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    helper = module.__file__
    code = ("import runpy,socket,time; "
            "socket.getaddrinfo=lambda *a,**kw: time.sleep(5); "
            f"runpy.run_path({helper!r},run_name='__main__')")
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    began = time.monotonic()
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=0.3)
    assert time.monotonic() - began < 0.8
    assert observer_payload(tmp_path, caught.value)["request_observation"]["phase"] == "open_response"
    assert_closed(processes)


def test_startup_stall_does_not_dispatch_and_worker_reaped(monkeypatch):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    code = f"import runpy,time;time.sleep(2);runpy.run_path({module.__file__!r},run_name='__main__')"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    with local_http() as (endpoint, calls), pytest.raises(rt.ModelRequestFailure):
        rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=0.2)
    assert calls == []
    assert_closed(processes)


def test_concurrent_calls_own_independent_workers(monkeypatch):
    processes, _ = spy_processes(monkeypatch)
    with local_http("body") as (slow, slow_calls), local_http() as (fast, fast_calls), ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(rt.OpenAICompatibleRuntime(slow, "fixture").complete, [], (), 0.3)
        two = pool.submit(rt.OpenAICompatibleRuntime(fast, "fixture").complete, [], (), 2)
        assert two.result(timeout=3) == rt.ModelTurn("done")
        with pytest.raises(rt.ModelRequestFailure):
            one.result(timeout=2)
    assert len(slow_calls) <= 1 and len(fast_calls) == 1 and len(processes) == 2
    assert_closed(processes)


def frames(*values):
    return b"".join(json.dumps(value).encode() + b"\n" for value in values)


def success_frames():
    return [
        {"kind": "phase", "phase": "open_response", "status": None},
        {"kind": "phase", "phase": "read_response_body", "status": 200},
        {"kind": "terminal", "outcome": "response", "cause": None, "reason": None,
         "status": 200, "body": base64.b64encode(b"{}").decode()},
    ]


@pytest.mark.parametrize("mutation", ["empty", "extra", "duplicate", "reverse", "phase_body", "status_bool",
                                     "status_mismatch", "base64", "cause", "reason", "unknown", "truncated"])
def test_protocol_rejects_malformed_inconsistent_and_extra_frames(mutation):
    module = transport()
    values = success_frames()
    if mutation == "empty":
        values = []
    elif mutation == "extra":
        values += values[-1:]
    elif mutation == "reverse":
        values[0], values[1] = values[1], values[0]
    elif mutation == "phase_body":
        values[0]["body"] = SECRET
    elif mutation == "status_bool":
        values[-1]["status"] = True
    elif mutation == "status_mismatch":
        values[-1]["status"] = 201
    elif mutation == "base64":
        values[-1]["body"] = "%%%"
    elif mutation == "cause":
        values[-1]["cause"] = "timeout"
    elif mutation == "reason":
        values[-1]["reason"] = "transport_timeout"
    elif mutation == "unknown":
        values[-1]["untrusted"] = SECRET
    raw = frames(*values)
    if mutation == "truncated":
        raw = raw[:-1]
    elif mutation == "duplicate":
        raw = raw.replace(b'"outcome": "response"', b'"outcome": "failure", "outcome": "response"')
    with pytest.raises((ValueError, TypeError)):
        module._decode_result(raw)


@pytest.mark.parametrize("phase,status,cause,reason,code", [
    ("open_response", None, "timeout", "transport_timeout", "timeout"),
    ("open_response", None, "url_timeout", "transport_timeout", "model_failed"),
    ("read_response_body", 200, "os_error", "transport_error", "model_failed"),
    ("read_http_error_body", 429, "http_error", "http_error", "model_http_failed"),
])
def test_safe_cross_process_projection_preserves_legacy_code(tmp_path, monkeypatch, phase, status, cause, reason, code):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    values = [{"kind": "phase", "phase": "open_response", "status": None}]
    if phase != "open_response":
        values.append({"kind": "phase", "phase": phase, "status": status})
    values.append({"kind": "terminal", "outcome": "failure", "cause": cause, "reason": reason,
                   "status": status, "body": ""})
    output = frames(*values)
    fixture = f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write({output!r})"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", fixture, str(fd)])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)
    payload = observer_payload(tmp_path, caught.value)
    assert payload["schema_version"] == "7" and payload["code"] == code
    assert payload["model_failure"] == {"reason": reason, "response_status": status}
    assert payload["request_observation"]["phase"] == phase
    assert_closed(processes)


def test_late_complete_response_is_rejected_after_protocol_validation(monkeypatch):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    original = module._decode_result

    def delayed(raw):
        value = original(raw)
        time.sleep(0.35)
        return value

    monkeypatch.setattr(module, "_decode_result", delayed)
    with local_http() as (endpoint, calls), pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=0.3)
    assert caught.value.evidence.reason == "transport_timeout" and len(calls) == 1
    assert_closed(processes)


def test_request_pipe_blockage_obeys_same_deadline(monkeypatch):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    fixture = "import time;time.sleep(3)"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", fixture, str(fd)])
    began = time.monotonic()
    with pytest.raises(rt.ModelRequestFailure):
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete(
            [{"role": "user", "content": "x" * (1024 * 1024)}], timeout=0.3,
        )
    assert time.monotonic() - began < 0.8
    assert_closed(processes)


def test_request_size_rejected_before_launch(monkeypatch):
    module = transport()
    monkeypatch.setattr(module, "MAX_REQUEST_BYTES", 64)
    monkeypatch.setattr(module, "Popen", lambda *a, **kw: pytest.fail("oversize request must not launch"))
    with pytest.raises(ValueError, match="64 MiB"):
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)


@pytest.mark.parametrize("fixture", ["print('not json')", "print('x' * 513)", "raise SystemExit(7)"])
def test_bad_or_crashed_child_cannot_become_response(monkeypatch, fixture):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    monkeypatch.setattr(module, "MAX_RESULT_BYTES", 512)
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", fixture, str(fd)])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)
    assert caught.value.evidence.reason == "transport_error"
    assert_closed(processes)


def test_caller_exception_still_kills_reaps_and_closes_every_owned_fd(monkeypatch):
    module = transport()
    processes, _ = spy_processes(monkeypatch)
    original_spawn = module.Popen
    pipes = []
    original_pipe = module.os.pipe

    def pipe():
        pair = original_pipe()
        pipes.append(pair)
        return pair

    def spawn(*args, **kwargs):
        process = original_spawn(*args, **kwargs)

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt()

        process.communicate = interrupted
        return process

    monkeypatch.setattr(module.os, "pipe", pipe)
    monkeypatch.setattr(module, "Popen", spawn)
    with local_http() as (endpoint, _), pytest.raises(KeyboardInterrupt):
        rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=2)
    assert_closed(processes)
    for pair in pipes:
        for fd in pair:
            with pytest.raises(OSError):
                os.fstat(fd)


def test_parent_single_pid_death_closes_lifeline_and_worker_socket(tmp_path):
    module = transport()
    disconnected = threading.Event()
    source = str(Path(module.__file__).resolve().parents[1])
    with local_http("body", disconnected=disconnected) as (endpoint, calls):
        code = (
            "import json,os;from lunar_evolution import http_transport as h;from lunar_evolution.runtime import OpenAICompatibleRuntime;"
            "original=h.Popen;"
            "exec('def spawn(*a,**kw):\\n p=original(*a,**kw)\\n print(json.dumps({\"pid\":p.pid,\"pgid\":os.getpgid(p.pid)}),flush=True)\\n return p');"
            "h.Popen=spawn;"
            f"OpenAICompatibleRuntime({endpoint!r},'fixture').complete([],timeout=20)"
        )
        parent = subprocess.Popen([sys.executable, "-B", "-c", code], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env={"PYTHONPATH": source}, start_new_session=True)
        try:
            ready, _, _ = select.select([parent.stdout], [], [], 3)
            assert ready
            child = json.loads(parent.stdout.readline())
            assert child["pgid"] == parent.pid
            end = time.monotonic() + 3
            while not calls and time.monotonic() < end:
                time.sleep(0.01)
            assert len(calls) == 1
            parent.kill()  # Deliberately only the parent's PID, not its inherited process group.
            parent.communicate(timeout=2)
            assert disconnected.wait(2), "guardian must close worker socket after parent death"
            end = time.monotonic() + 2
            while True:
                observed = subprocess.run(["ps", "-p", str(child["pid"]), "-o", "stat="],
                                          capture_output=True, text=True, timeout=2, check=False)
                state = observed.stdout.strip()
                # An exited orphan can await the host's init reaper; a zombie cannot send HTTP.
                if not state or state.startswith("Z") or time.monotonic() >= end:
                    break
                time.sleep(0.01)
            assert not state or state.startswith("Z"), "worker must exit before test cleanup"
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            try:
                os.killpg(parent.pid, signal.SIGKILL)  # Test-owned, isolated group only.
            except ProcessLookupError:
                pass
            parent.stdout.close()


def clear_proxy_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.lower().endswith("_proxy") or name == "REQUEST_METHOD":
            monkeypatch.delenv(name)


@pytest.mark.parametrize("bypass", [True, False])
def test_environment_no_proxy_is_projected_without_proxy_values_in_child_env(monkeypatch, bypass):
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "127.0.0.1" if bypass else "not-matched.invalid")
    with local_http() as (endpoint, calls):
        model = rt.OpenAICompatibleRuntime(endpoint, "fixture")
        if bypass:
            assert model.complete([], timeout=2) == rt.ModelTurn("done")
            assert len(calls) == 1
        else:
            with pytest.raises(rt.ModelRequestFailure):
                model.complete([], timeout=2)
            assert calls == []


def test_environment_proxy_bypass_rechecked_for_redirect_host(monkeypatch):
    clear_proxy_environment(monkeypatch)
    proxy_calls = []

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            proxy_calls.append(self.path)
            raw = b'{"choices":[{"message":{"content":"via proxy"}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302)
            self.send_header("Location", "http://localhost:1/redirected")
            self.send_header("Content-Length", "0")
            self.end_headers()

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), cls) for cls in (Proxy, Redirect)]
    threads = [threading.Thread(target=lambda s=s: s.serve_forever(poll_interval=0.01)) for s in servers]
    for thread in threads:
        thread.start()
    try:
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{servers[0].server_port}")
        monkeypatch.setenv("no_proxy", "127.0.0.1")
        assert rt.OpenAICompatibleRuntime(f"http://127.0.0.1:{servers[1].server_port}", "fixture").complete([], timeout=2) == rt.ModelTurn("via proxy")
        assert proxy_calls == ["http://localhost:1/redirected"]
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


def test_url_reason_timeout_and_cause_timeout_remain_distinct():
    from urllib.error import URLError

    module = transport()
    wrapped = URLError(TimeoutError("fixture"))
    assert module._transport_cause(wrapped) == "url_timeout"
    chained = URLError("fixture")
    chained.__cause__ = TimeoutError("fixture")
    assert module._transport_cause(chained) == "timeout"


def test_spawn_failure_closes_lifeline_and_does_not_fallback(monkeypatch):
    module = transport()
    pipes = []
    original_pipe = module.os.pipe

    def pipe():
        pair = original_pipe()
        pipes.append(pair)
        return pair

    def failed(*args, **kwargs):
        raise OSError(SECRET)

    monkeypatch.setattr(module.os, "pipe", pipe)
    monkeypatch.setattr(module, "Popen", failed)
    monkeypatch.setattr(rt, "urlopen", lambda *a, **kw: pytest.fail("no transport fallback"))
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)
    assert SECRET not in str(caught.value)
    for pair in pipes:
        for fd in pair:
            with pytest.raises(OSError):
                os.fstat(fd)


def test_response_and_error_body_limits_are_independently_checked(monkeypatch):
    module = transport()
    monkeypatch.setattr(module, "MAX_BODY_BYTES", 1)
    with pytest.raises(ValueError):
        module._decode_result(frames(*success_frames()))
    values = success_frames()
    values[1].update(phase="read_http_error_body", status=503)
    values[-1].update(outcome="failure", cause="http_error", reason="http_error", status=503,
                      body=base64.b64encode(b"x" * 2001).decode())
    with pytest.raises(ValueError):
        module._decode_result(frames(*values))


def test_delayed_worker_checks_deadline_before_http(monkeypatch):
    module = transport()
    code = (f"import runpy;g=runpy.run_path({module.__file__!r},run_name='fixture');"
            "g['_worker'].__globals__['monotonic']=lambda:1e100;"
            "g['_worker'](int(__import__('sys').argv[1]))")
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    with local_http() as (endpoint, calls), pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=2)
    assert calls == [] and caught.value.evidence.reason == "transport_timeout"


def test_worker_lifeline_supports_descriptor_above_select_fd_limit(monkeypatch):
    import fcntl
    import resource

    module = transport()
    original_pipe = module.os.pipe
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    required = 1100
    if hard != resource.RLIM_INFINITY and hard < required:
        pytest.skip("host descriptor hard limit cannot exercise fd >= 1024")
    if soft < required:
        resource.setrlimit(resource.RLIMIT_NOFILE, (required, hard))
    count = 0

    def pipe():
        nonlocal count
        read, write = original_pipe()
        count += 1
        if count == 1:  # Only the transport lifeline; leave Popen's own pipes unchanged.
            high = fcntl.fcntl(read, fcntl.F_DUPFD, 1024)
            os.close(read)
            return high, write
        return read, write

    monkeypatch.setattr(module.os, "pipe", pipe)
    try:
        with local_http() as (endpoint, calls):
            assert rt.OpenAICompatibleRuntime(endpoint, "fixture").complete([], timeout=2) == rt.ModelTurn("done")
        assert len(calls) == 1
    finally:
        if soft < required:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_late_failure_projection_also_checks_transport_deadline(monkeypatch):
    module = transport()
    values = success_frames()
    values[-1].update(outcome="failure", reason="transport_error", cause="os_error", body="")
    output = frames(*values)
    code = f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write({output!r})"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    original = module._decode_result

    def delayed(raw):
        time.sleep(0.35)
        return original(raw)

    monkeypatch.setattr(module, "_decode_result", delayed)
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=0.3)
    assert caught.value.evidence.reason == "transport_timeout"


def test_deeply_nested_malformed_worker_ipc_is_a_safe_typed_failure(monkeypatch):
    module = transport()
    output = frames(*success_frames()[:2])
    output += (b'{"kind":"terminal","outcome":"response","reason":null,"cause":null,'
               b'"status":200,"body":' + b'[' * 20000 + b'0' + b']' * 20000 + b'}\n')
    code = f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write({output!r})"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)
    assert caught.value.evidence.reason == "transport_error"
    assert str(caught.value) == "could not reach model endpoint: HTTP transport failed"


@pytest.mark.parametrize("layers", [0, 6, 7, 8])
@pytest.mark.parametrize("root_kind", ["os_error", "url_reason", "url_cause", "branch_difference"])
def test_transport_projection_preserves_native_legacy_cause_visibility(tmp_path, monkeypatch, layers, root_kind):
    from urllib.error import URLError

    module = transport()
    error = TimeoutError("fixture")
    if root_kind == "url_reason":
        error = URLError(error)
    elif root_kind == "url_cause":
        outer = URLError("fixture")
        outer.__cause__ = error
        error = outer
    elif root_kind == "branch_difference":
        url = URLError(OSError("fixture"))
        url.__cause__ = error
        error = OSError("fixture")
        error.__cause__ = url
    for _ in range(layers):
        outer = OSError("fixture")
        outer.__cause__ = error
        error = outer
    reason = rt._transport_failure_reason(error)
    legacy = rt.ModelRequestFailure("fixture", reason)
    legacy.__cause__ = error
    expected = observer_payload(tmp_path, legacy)
    cause = module._transport_cause(error)
    assert module._CAUSE_REASONS[cause] == reason
    values = [success_frames()[0], {
        "kind": "terminal", "outcome": "failure", "cause": cause, "reason": reason,
        "status": None, "body": "",
    }]
    output = frames(*values)
    code = f"import sys;sys.stdin.buffer.read();sys.stdout.buffer.write({output!r})"
    monkeypatch.setattr(module, "_worker_command", lambda fd: [sys.executable, "-I", "-S", "-B", "-c", code, str(fd)])
    with pytest.raises(rt.ModelRequestFailure) as caught:
        rt.OpenAICompatibleRuntime("http://fixture.invalid", "fixture").complete([], timeout=2)
    projected = observer_payload(tmp_path, caught.value)
    assert projected["code"] == expected["code"]
    assert projected["model_failure"] == expected["model_failure"]
