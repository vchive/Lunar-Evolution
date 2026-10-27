"""Execute only new adapter code and existing Lunar IPC code with inert local data.

No upstream module or function is imported/executed. Synthetic literal prompt data supplies formatting placeholders. Every upstream function is an execution-forbidden
sentinel. These tests cannot prove diff semantics or accepted runtime behavior.
"""

import ast
import base64
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def adapter():
    source = ROOT / "tools/openevolve_fixed_profile/assets/fixed_entrypoint.py"
    tree = ast.parse(source.read_bytes())
    removed = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module.startswith("openevolve.")]
    assert len(removed) == 3
    tree.body = [node for node in tree.body if node not in removed]
    # Synthetic data tests only our mapping; actual upstream prompt semantics stay unrun.
    values = {
        "BASE_SYSTEM_TEMPLATE": "synthetic system fixture",
        "DIFF_USER_TEMPLATE": (
            "{metrics}\n{improvement_areas}\n{artifacts}\n{evolution_history}\n"
            "{language}\n{current_program}"
        ),
    }
    upstream_calls = []

    def forbidden(*_args, **_kwargs):
        upstream_calls.append(1)
        raise AssertionError("upstream function execution is forbidden")

    namespace = {
        "__name__": "new_adapter_source_only_fixture", "__file__": str(source),
        "brokered_producer_post": forbidden, "extract_diffs": forbidden,
        "apply_diff_blocks": forbidden, "enforce_evolve_blocks": forbidden, **values,
    }
    # Deliberately execute only our new source after removing every upstream import.
    exec(compile(tree, str(source), "exec"), namespace)  # noqa: S102
    yield namespace
    assert upstream_calls == []


@pytest.fixture
def wires():
    memory = {
        "protocol": "lunar-rsi-learning-v1", "schema_version": "1",
        "snapshot_id": "original", "parent_snapshot_sha256": None, "items": [],
    }
    request = {
        "schema_version": "1", "kind": "rsi_solver_request", "episode_id": "original",
        "contract_sha256": "a" * 64, "evaluator_sha256": "b" * 64,
        "environment_sha256": "c" * 64,
        "memory_snapshot_sha256": hashlib.sha256(canonical(memory)).hexdigest(),
        "solver_id": "openevolve", "solver_settings": {
            "model": "fixture-model", "initial_program": "def solve(x):\n    return x + 0\n",
            "task": "Remove redundant work while preserving results.",
        }, "budget": {"deadline_unix": time.time() + 30}, "practice_charter": {},
    }
    return request, memory


def test_original_request_and_synthetic_template_reach_one_inert_rejected_http_call(adapter, wires):
    request, memory = wires
    calls = []

    def post(request_id, body, *, deadline_ns):
        calls.append((request_id, json.loads(body), deadline_ns))
        return 503, b"{}"

    with pytest.raises(adapter["FixedProfileError"], match="http_failed"):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9, post=post)
    assert len(calls) == 1
    assert calls[0][0] == "req-1"
    body = calls[0][1]
    assert body["model"] == "fixture-model"
    assert body["n"] == 1 and body["stream"] is False
    assert request["solver_settings"]["initial_program"] in body["messages"][1]["content"]
    assert request["solver_settings"]["task"] in body["messages"][1]["content"]


@pytest.mark.parametrize("key", ["evaluator", "module", "command", "provider", "template_dir", "checkpoint"])
def test_dynamic_settings_refused_before_upstream_or_broker(adapter, wires, key):
    request, memory = wires
    request["solver_settings"][key] = "forbidden"
    with pytest.raises(adapter["FixedProfileError"], match="settings_invalid"):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9)


def test_changed_memory_pin_refused_before_upstream_or_broker(adapter, wires):
    request, memory = wires
    memory["snapshot_id"] = "changed"
    with pytest.raises(adapter["FixedProfileError"], match="memory_pin_mismatch"):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9)


@pytest.mark.parametrize("kind", ["noncanonical", "duplicate", "oversize", "deep"])
def test_json_envelope_boundaries_before_upstream(adapter, wires, kind):
    request, memory = wires
    raw = canonical(request)
    if kind == "noncanonical":
        raw += b"\n"
    elif kind == "duplicate":
        raw = b'{"a":1,"a":2}'
    elif kind == "oversize":
        raw = b"x" * (128 * 1024 + 1)
    else:
        request["practice_charter"] = {"x": [[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]}
        raw = canonical(request)
    with pytest.raises(adapter["FixedProfileError"]):
        adapter["_inputs"](raw, canonical(memory))


@pytest.mark.parametrize("kind", ["program_bytes", "program_lines", "task_bytes", "expired", "missing_deadline"])
def test_profile_limits_before_upstream_or_broker(adapter, wires, kind):
    request, memory = wires
    if kind == "program_bytes":
        request["solver_settings"]["initial_program"] = "x" * (32 * 1024 + 1)
    elif kind == "program_lines":
        request["solver_settings"]["initial_program"] = "x\n" * 2049
    elif kind == "task_bytes":
        request["solver_settings"]["task"] = "x" * (8 * 1024 + 1)
    elif kind == "expired":
        request["budget"]["deadline_unix"] = time.time() - 1
    else:
        request["budget"] = {}
    with pytest.raises(adapter["FixedProfileError"]):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9)


@pytest.mark.parametrize("reply", [
    b"{", b"x" * (64 * 1024 + 1),
    b'{"choices":[{"finish_reason":"length","message":{"role":"assistant","content":"x"}}]}',
    b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"x","tool_calls":[{}]}}]}',
])
def test_bad_replies_refused_before_upstream_diff_function(adapter, wires, reply):
    request, _memory = wires
    with pytest.raises(adapter["FixedProfileError"]):
        adapter["_candidate"](request, reply)


def test_fixed_main_reads_only_original_two_grants_and_preserves_output_on_http_failure(adapter, wires, tmp_path, monkeypatch):
    request, memory = wires
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / ".rsi-input").mkdir()
    for name, value in (("request.json", request), ("memory.json", memory)):
        path = tmp_path / ".rsi-input" / name
        path.write_bytes(canonical(value))
        path.chmod(0o400)
    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return 503, b"{}"

    adapter["brokered_producer_post"] = post
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(adapter["FixedProfileError"], match="http_failed"):
        adapter["main"](["--lunar-rsi-input-v1", "e" * 64])
    assert len(calls) == 1
    assert list((tmp_path / "output").iterdir()) == []
    assert not (tmp_path / ".rsi-input" / "manifest.json").exists()


@pytest.mark.parametrize("kind", ["symlink", "mode", "hardlink", "fifo"])
def test_original_grant_file_refusals(adapter, tmp_path, kind):
    raw = tmp_path / "request.json"
    raw.write_bytes(b"{}")
    raw.chmod(0o400)
    if kind == "symlink":
        original = tmp_path / "original"
        raw.rename(original)
        raw.symlink_to(original)
    elif kind == "mode":
        raw.chmod(0o600)
    elif kind == "hardlink":
        os.link(raw, tmp_path / "other")
    else:
        raw.unlink()
        os.mkfifo(raw)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises((OSError, adapter["FixedProfileError"])):
            adapter["_read_at"](descriptor, "request.json")
    finally:
        os.close(descriptor)


def test_create_only_wrapper_collision_preserves_first_bytes(adapter, tmp_path):
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        adapter["_write_at"](descriptor, "result.json", b"first")
        with pytest.raises(FileExistsError):
            adapter["_write_at"](descriptor, "result.json", b"second")
        assert (tmp_path / "result.json").read_bytes() == b"first"
    finally:
        os.close(descriptor)


@pytest.fixture
def broker():
    from tools.openevolve_fixed_profile.prepare import generate_target_broker

    # Generate exact reviewed existing Lunar source, without importing its host package.
    source, _segments = generate_target_broker(
        (ROOT / "src/lunar_evolution/producer_broker_ipc.py").read_bytes(),
        (ROOT / "src/lunar_evolution/http_transport.py").read_bytes(),
    )
    namespace = {"__name__": "existing_lunar_broker_source_fixture"}
    # Existing Lunar client source only: stdlib plus inert anonymous pipes.
    exec(compile(ast.parse(source), "generated_broker_fixture", "exec"), namespace)  # noqa: S102
    return namespace


@pytest.mark.parametrize("raw", [b"{}", b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b"[]\n"])
def test_existing_broker_frame_invalid_or_duplicate_or_nonfinite(broker, raw):
    with pytest.raises(broker["ProducerBrokerIpcError"]):
        broker["_decode"](raw, limit=1024)


def test_existing_broker_request_response_roundtrip_uses_only_local_anonymous_pipes(broker, monkeypatch):
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    try:
        monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(request_write))
        monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", str(response_read))
        frame = {
            "protocol": "lunar-producer-broker-ipc-v1", "request_id": "req-1",
            "status": "completed", "http_status": 200,
            "body_base64": base64.b64encode(b"inert-fixture-response").decode(),
        }
        os.write(response_write, canonical(frame) + b"\n")
        status, body = broker["brokered_producer_post"]("req-1", b"{}", deadline_ns=time.monotonic_ns() + 10**9)
        assert (status, body) == (200, b"inert-fixture-response")
        sent = json.loads(os.read(request_read, 4096))
        assert sent == {"protocol": "lunar-producer-broker-ipc-v1", "request_id": "req-1", "body_base64": "e30="}
    finally:
        for descriptor in (request_read, request_write, response_read, response_write):
            os.close(descriptor)


@pytest.mark.parametrize("kind", ["eof", "truncated", "multiline", "oversize", "expired"])
def test_existing_broker_partial_eof_bounds_and_deadline(broker, kind):
    read_fd, write_fd = os.pipe()
    try:
        data = {"eof": b"", "truncated": b"{", "multiline": b"{}\n{}\n", "oversize": b"x" * 10, "expired": b"{}\n"}[kind]
        if data:
            os.write(write_fd, data)
        os.close(write_fd)
        write_fd = None
        deadline_ns = time.monotonic_ns() - 1 if kind == "expired" else time.monotonic_ns() + 10**9
        if kind == "eof":
            assert broker["_read_line"](read_fd, deadline_ns, 8) is None
        else:
            with pytest.raises(broker["ProducerBrokerIpcError"]):
                broker["_read_line"](read_fd, deadline_ns, 8)
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def test_existing_broker_regular_file_fd_is_not_an_egress_channel(broker, tmp_path, monkeypatch):
    file = tmp_path / "not-a-pipe"
    file.write_bytes(b"fixture")
    descriptor = os.open(file, os.O_RDONLY)
    try:
        monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(descriptor))
        with pytest.raises(broker["ProducerBrokerIpcError"], match="pipe_invalid"):
            broker["_target_pipe"]("LUNAR_PRODUCER_REQUEST_FD")
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["request_id", "status", "http_bool", "body_base64"])
def test_existing_broker_response_identity_status_and_body_errors(broker, monkeypatch, kind):
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    try:
        monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(request_write))
        monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", str(response_read))
        frame = {"protocol": "lunar-producer-broker-ipc-v1", "request_id": "req-1", "status": "completed", "http_status": 200, "body_base64": "e30="}
        if kind == "request_id":
            frame["request_id"] = "foreign"
        elif kind == "status":
            frame["status"] = "unknown"
        elif kind == "http_bool":
            frame["http_status"] = True
        else:
            frame["body_base64"] = "invalid!"
        os.write(response_write, canonical(frame) + b"\n")
        with pytest.raises(broker["ProducerBrokerIpcError"]):
            broker["brokered_producer_post"]("req-1", b"{}", deadline_ns=time.monotonic_ns() + 10**9)
    finally:
        for descriptor in (request_read, request_write, response_read, response_write):
            os.close(descriptor)
