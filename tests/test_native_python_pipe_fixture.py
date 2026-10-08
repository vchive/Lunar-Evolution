"""Real CPython/SDK composition through original-v2, fixture-only native grants.

The sealed static launcher does not seal the installed interpreter, ELF loader
or stdlib. All cases are inert, use private anonymous pipes and capture actual
Python output; no provider, network connection or external evaluator is used.
"""

from __future__ import annotations

import base64
import json
import os
import sys

import pytest
from _native_python_fixture import (
    collect_python,
    prepare_python_fixture,
    read_request,
    respond,
    start_python_fixture,
)
from test_native_trusted_controller_death import _frame

from lunar_evolution.http_transport import MAX_RESULT_BYTES

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux CPython pipe fixture")

_PROTOCOL = "lunar-producer-broker-ipc-v1"
_REQUEST_ID = "native-python-fixture-1"
_SCRIPT = r'''
import errno
import fcntl
import importlib
import json
import os
import stat
import sys
import time
from pathlib import Path

sdk, decoy, output, deadline_arg, mode = sys.argv[1:]
deadline_ns = int(deadline_arg)
assert deadline_ns > time.monotonic_ns()
read_fd = int(os.environ["LUNAR_PRODUCER_RESPONSE_FD"])
write_fd = int(os.environ["LUNAR_PRODUCER_REQUEST_FD"])
assert read_fd != write_fd
assert os.environ["LUNAR_BOOTSTRAP_RELEASED"] == "1"
assert os.environ["PYTHONPATH"] == decoy
assert os.environ["PYTHONUSERBASE"] == decoy
expected_environment = {
    "PATH", "LANG", "LUNAR_BOOTSTRAP_RELEASED", "LUNAR_PRODUCER_RESPONSE_FD",
    "LUNAR_PRODUCER_REQUEST_FD", "PYTHONPATH", "PYTHONUSERBASE",
}
# CPython may coerce LANG=C and add LC_CTYPE during initialization.
assert expected_environment <= set(os.environ) <= expected_environment | {"LC_CTYPE"}
inherited = []
for fd in range(3, 4096):
    try:
        os.fstat(fd)
    except OSError as exc:
        assert exc.errno == errno.EBADF
    else:
        inherited.append(fd)
assert inherited == sorted((read_fd, write_fd))
assert stat.S_ISFIFO(os.fstat(read_fd).st_mode)
assert stat.S_ISFIFO(os.fstat(write_fd).st_mode)
assert fcntl.fcntl(read_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
assert fcntl.fcntl(write_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_WRONLY
flags = {name: getattr(sys.flags, name) for name in (
    "isolated", "ignore_environment", "no_site", "no_user_site", "dont_write_bytecode", "safe_path",
)}
assert all(value == 1 for value in flags.values())
assert sys.dont_write_bytecode is True
assert "site" not in sys.modules
assert "sitecustomize" not in sys.modules and "usercustomize" not in sys.modules
initial_path = tuple(sys.path)
assert "" not in initial_path
for excluded in (str(Path.cwd()), str(Path(__file__).parent), sdk, decoy):
    assert excluded not in initial_path
# The decoys are readable and valid Python. Isolated imports must ignore them.
for directory in (Path.cwd(), Path(__file__).parent, Path(decoy)):
    assert (directory / "lunar_decoy.py").read_text().endswith("VALUE = 42\n")
for name in ("lunar_decoy", "sitecustomize", "usercustomize"):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        assert exc.name == name
    else:
        raise AssertionError("isolated fixture imported a customization decoy")
try:
    (Path.cwd().parent / "ungranted-sentinel").read_bytes()
except PermissionError:
    sentinel_denied = True
else:
    raise AssertionError("ungranted fixture bytes were readable")
# This explicit fixture source grant is deliberately distinct from cwd import.
sys.path.insert(0, sdk)
from lunar_evolution.producer_broker_ipc import ProducerBrokerIpcError, brokered_producer_post

owned = {read_fd, write_fd}
try:
    if mode == "missing-read":
        del os.environ["LUNAR_PRODUCER_RESPONSE_FD"]
    elif mode == "missing-write":
        del os.environ["LUNAR_PRODUCER_REQUEST_FD"]
    elif mode == "same":
        os.environ["LUNAR_PRODUCER_REQUEST_FD"] = str(read_fd)
    elif mode == "regular":
        replacement = os.open(__file__, os.O_RDONLY)
        owned.add(replacement)
        os.environ["LUNAR_PRODUCER_RESPONSE_FD"] = str(replacement)
    elif mode == "closed-read":
        os.close(read_fd)
        owned.remove(read_fd)
    elif mode == "closed-write":
        os.close(write_fd)
        owned.remove(write_fd)
    elif mode != "plain":
        raise AssertionError("unsupported inert fixture mode")
    try:
        status, body = brokered_producer_post(
            "native-python-fixture-1", b"inert-ping", deadline_ns=deadline_ns,
        )
    except ProducerBrokerIpcError as exc:
        result = {"error": exc.code}
    else:
        result = {"http_status": status, "body": body.decode("ascii")}
finally:
    for fd in owned:
        os.close(fd)
Path("python-work-marker").write_bytes(b"inert-python-work")
(Path(output) / "python-output-marker").write_bytes(b"inert-python-output")
print("inert-python-stderr", file=sys.stderr, flush=True)
print(json.dumps({
    "scope": "trusted-host-fixture-only", "runtime_load_protection": False,
    "interpreter_load_binding": "trusted-host-fixture-only",
    "version": list(sys.version_info[:3]), "cache_tag": sys.implementation.cache_tag,
    "flags": flags, "inherited": inherited, "read_fd": read_fd, "write_fd": write_fd,
    "deadline_ns": deadline_ns, "sentinel_denied": sentinel_denied, "result": result,
}, sort_keys=True, separators=(",", ":")), flush=True)
'''


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    return prepare_python_fixture(tmp_path_factory.mktemp("native-python-host-fixture"))


def _release(fixture):
    ready = _frame(fixture.frame)
    assert ready.kind == "bootstrap_ready" and ready.sequence == 1
    assert ready.launch_sha256 == fixture.launch.launch_sha256
    assert ready.intent_sha256 == fixture.launch.intent_sha256
    assert not (fixture.working / "python-work-marker").exists()
    os.write(fixture.gate, b"1")
    fixture.close(fixture.gate)
    started = _frame(fixture.frame)
    assert started.kind == "target_started" and started.sequence == 2
    assert started.launch_sha256 == fixture.launch.launch_sha256
    assert started.intent_sha256 == fixture.launch.intent_sha256
    assert started.target_executable_identity == fixture.launch.target_executable_identity
    assert started.observed_pgid == fixture.process.pid
    assert started.observed_pid != fixture.process.pid


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _response(**overrides):
    value = {
        "protocol": _PROTOCOL, "request_id": _REQUEST_ID, "status": "completed",
        "http_status": 200, "body_base64": base64.b64encode(b"inert-pong").decode("ascii"),
    }
    value.update(overrides)
    return value


def _assert_request(fixture):
    assert read_request(fixture) == _encode({
        "protocol": _PROTOCOL, "request_id": _REQUEST_ID,
        "body_base64": base64.b64encode(b"inert-ping").decode("ascii"),
    })


def _assert_result(fixture, prepared, expected):
    terminal = _frame(fixture.frame)
    assert terminal.kind == "terminal" and terminal.sequence == 3
    assert terminal.launch_sha256 == fixture.launch.launch_sha256
    assert terminal.intent_sha256 == fixture.launch.intent_sha256
    stdout, stderr = collect_python(fixture)
    assert fixture.process.returncode == 0, stderr
    assert stderr == b"inert-python-stderr\n"
    observed = json.loads(stdout)
    assert stdout == _encode(observed)
    assert observed == {
        "scope": "trusted-host-fixture-only", "runtime_load_protection": False,
        "interpreter_load_binding": "trusted-host-fixture-only",
        "version": list(sys.version_info[:3]), "cache_tag": sys.implementation.cache_tag,
        "flags": {name: 1 for name in (
            "isolated", "ignore_environment", "no_site", "no_user_site", "dont_write_bytecode", "safe_path",
        )},
        "inherited": sorted((fixture.target_response_fd, fixture.target_request_fd)),
        "read_fd": fixture.target_response_fd, "write_fd": fixture.target_request_fd,
        "deadline_ns": fixture.deadline_ns, "sentinel_denied": True, "result": expected,
    }
    assert observed["read_fd"] != observed["write_fd"]
    assert (fixture.working / "python-work-marker").read_bytes() == b"inert-python-work"
    assert (fixture.output / "python-output-marker").read_bytes() == b"inert-python-output"
    assert fixture.sentinel.read_bytes() == b"private fixture bytes"
    for root in (fixture.working, fixture.inputs, fixture.output, fixture.decoy, prepared.sdk):
        assert not tuple(root.rglob("*.pyc"))
        assert not tuple(root.rglob("__pycache__"))
    for name in ("lunar_decoy", "sitecustomize", "usercustomize"):
        assert not (fixture.working / f"{name}-loaded").exists()


def test_actual_python_sdk_pipe_flags_stdio_and_original_fd_closure(tmp_path, prepared):
    with start_python_fixture(tmp_path, prepared, _SCRIPT) as fixture:
        _release(fixture)
        _assert_request(fixture)
        respond(fixture, _encode(_response()))
        _assert_result(fixture, prepared, {"http_status": 200, "body": "inert-pong"})
    assert fixture.process.returncode == 0
    assert not fixture.owned_fds


@pytest.mark.parametrize("case, expected", [
    ("wrong-id", "producer_broker_response_invalid"),
    ("wrong-protocol", "producer_broker_response_invalid"),
    ("wrong-status", "producer_broker_response_invalid"),
    ("http-status-bool", "producer_broker_response_invalid"),
    ("http-status-outside", "producer_broker_response_invalid"),
    ("missing-key", "producer_broker_response_invalid"),
    ("extra-key", "producer_broker_response_invalid"),
    ("duplicate-key", "producer_broker_frame_invalid"),
    ("malformed", "producer_broker_frame_invalid"),
    ("not-object", "producer_broker_frame_invalid"),
    ("truncated", "producer_broker_frame_truncated"),
    ("missing", "producer_broker_response_missing"),
    ("oversize", "producer_broker_frame_too_large"),
    ("invalid-base64", "producer_broker_body_invalid"),
    ("wrong-body-type", "producer_broker_body_invalid"),
])
def test_actual_python_sdk_response_refusals(tmp_path, prepared, case, expected):
    value = _response()
    if case == "wrong-id":
        value["request_id"] = "other-inert-request"
    elif case == "wrong-protocol":
        value["protocol"] = "fixture-invalid-protocol"
    elif case == "wrong-status":
        value["status"] = "timed_out"
    elif case == "http-status-bool":
        value["http_status"] = True
    elif case == "http-status-outside":
        value["http_status"] = 600
    elif case == "missing-key":
        del value["status"]
    elif case == "extra-key":
        value["fixture_extra"] = 1
    elif case == "invalid-base64":
        value["body_base64"] = "!fixture-invalid!"
    elif case == "wrong-body-type":
        value["body_base64"] = None
    raw = _encode(value)
    if case == "duplicate-key":
        raw = raw[:-2] + b',"status":"completed"}\n'
    elif case == "malformed":
        raw = b"{\n"
    elif case == "not-object":
        raw = b"[]\n"
    elif case == "truncated":
        raw = b"{"
    elif case == "missing":
        raw = b""
    elif case == "oversize":
        raw = b"x" * (MAX_RESULT_BYTES * 4 // 3 + 4097)
    with start_python_fixture(tmp_path, prepared, _SCRIPT) as fixture:
        _release(fixture)
        _assert_request(fixture)
        respond(fixture, raw)
        _assert_result(fixture, prepared, {"error": expected})
    assert fixture.process.returncode == 0
    assert not fixture.owned_fds


@pytest.mark.parametrize("mode", [
    "missing-read", "missing-write", "same", "regular", "closed-read", "closed-write",
])
def test_actual_python_sdk_refuses_invalid_endpoint_before_request(tmp_path, prepared, mode):
    # Direction validation remains the original C boundary's responsibility;
    # this deliberately tests only fixed-code SDK endpoint failures it defines.
    with start_python_fixture(tmp_path, prepared, _SCRIPT, mode=mode) as fixture:
        _release(fixture)
        _assert_result(fixture, prepared, {"error": "producer_broker_pipe_invalid"})
        assert os.read(fixture.request, 1) == b""
    assert fixture.process.returncode == 0
    assert not fixture.owned_fds


@pytest.mark.parametrize("fault", ["reversed", "same", "regular"])
def test_original_v2_endpoint_refusal_does_not_start_python(tmp_path, prepared, fault):
    with start_python_fixture(tmp_path, prepared, _SCRIPT, endpoint_fault=fault) as fixture:
        stdout, stderr = collect_python(fixture)
        assert fixture.process.returncode == 73, stderr
        assert stdout == b""
        assert os.read(fixture.frame, 1) == b""
        assert os.read(fixture.request, 1) == b""
        assert not (fixture.working / "python-work-marker").exists()
        assert not (fixture.output / "python-output-marker").exists()
    assert not fixture.owned_fds
