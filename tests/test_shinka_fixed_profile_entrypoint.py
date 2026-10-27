"""Execute only new adapter code and existing Lunar IPC code with inert local data.

No upstream module or function is imported/executed. Synthetic literal prompt data supplies formatting placeholders. Every upstream function is an execution-forbidden
sentinel. These tests cannot prove diff semantics or accepted runtime behavior.
"""

import ast
import hashlib
import json
import os
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = "# immutable header\n# EVOLVE-BLOCK-START\ndef solve(x):\n    return x + 0\n# EVOLVE-BLOCK-END\n# immutable footer\n"
CHANGED = ORIGINAL.replace("return x + 0", "return x")
SYNTHETIC_DIFF = "<<<<<<< SEARCH\nreturn x + 0\n=======\nreturn x\n>>>>>>> REPLACE"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def adapter():
    source = ROOT / "tools/shinka_fixed_profile/assets/fixed_entrypoint.py"
    tree = ast.parse(source.read_bytes())
    removed = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module.startswith("shinka.")]
    assert len(removed) == 4
    tree.body = [node for node in tree.body if node not in removed]
    # Synthetic data tests only our mapping; actual upstream prompt semantics stay unrun.
    values = {
        "DIFF_SYS_FORMAT": "synthetic diff system fixture",
        "DIFF_ITER_MSG": "{language}\n{code_content}\n{performance_metrics}\n{text_feedback_section}",
        "PATCH_PATTERN": re.compile(
            r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.DOTALL,
        ),
        "PatchError": ValueError,
    }
    upstream_calls = []

    def forbidden(*_args, **_kwargs):
        upstream_calls.append(1)
        raise AssertionError("upstream function execution is forbidden")

    namespace = {
        "__name__": "new_adapter_source_only_fixture", "__file__": str(source),
        "brokered_producer_post": forbidden, "apply_search_replace": forbidden,
        "validate_evolve_markers": forbidden, **values,
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
        "solver_id": "shinka", "solver_settings": {
            "model": "fixture-model", "initial_program": ORIGINAL,
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


def test_create_only_source_collision_preserves_first_bytes(adapter, tmp_path):
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        adapter["_write_at"](descriptor, "main.py", b"first")
        with pytest.raises(FileExistsError):
            adapter["_write_at"](descriptor, "main.py", b"second")
        assert (tmp_path / "main.py").read_bytes() == b"first"
    finally:
        os.close(descriptor)



def reply(content=SYNTHETIC_DIFF):
    return canonical({"choices": [{
        "finish_reason": "stop", "message": {"role": "assistant", "content": content},
    }]})


def install_artificial_diff_doubles(adapter, *, candidate=CHANGED, applied=1, validation=None):
    """Only artificial return values: actual Shinka diff semantics remain unexecuted."""
    calls = []

    def apply(content, original, *, strict):
        calls.append(("apply", content, original, strict))
        return candidate, applied

    def validate(content, language):
        calls.append(("validate", content, language))
        return validation

    adapter.update(apply_search_replace=apply, validate_evolve_markers=validate)
    return calls


@pytest.mark.parametrize("program", [
    "def solve(x): return x", "# EVOLVE-BLOCK-END\n# EVOLVE-BLOCK-START\n",
    ORIGINAL + "# EVOLVE-BLOCK-START\n", ORIGINAL.replace("# EVOLVE-BLOCK", "// EVOLVE-BLOCK"),
])
def test_single_python_region_is_required_before_broker(adapter, wires, program):
    request, memory = wires
    request["solver_settings"]["initial_program"] = program
    with pytest.raises(adapter["FixedProfileError"], match="regions_invalid"):
        adapter["propose"](canonical(request), canonical(memory), deadline_ns=time.monotonic_ns() + 10**9)


@pytest.mark.parametrize("content", [
    "no diff", SYNTHETIC_DIFF.replace("return x + 0", ""),
    SYNTHETIC_DIFF + "\n<<<<<<< SEARCH\nunclosed",
    SYNTHETIC_DIFF + "\n# EVOLVE-BLOCK-START",
    (SYNTHETIC_DIFF + "\n") * 17,
])
def test_bounded_closed_diff_form_refused_before_upstream(adapter, wires, content):
    request, _memory = wires
    with pytest.raises(adapter["FixedProfileError"], match="diff_invalid"):
        adapter["_candidate"](request, reply(content))


def test_artificial_diff_orchestration_checks_exact_immutable_bytes(adapter, wires):
    request, _memory = wires
    calls = install_artificial_diff_doubles(adapter)
    assert adapter["_candidate"](request, reply()) == CHANGED.encode()
    assert [call[0] for call in calls] == ["apply", "validate"]
    assert calls[0][3] is True


@pytest.mark.parametrize("kind", ["unmatched", "unchanged", "prefix", "suffix", "marker_validation"])
def test_artificial_diff_refuses_incomplete_or_immutable_candidate(adapter, wires, kind):
    request, _memory = wires
    candidate, applied, validation = CHANGED, 1, None
    if kind == "unmatched":
        applied = 0
    elif kind == "unchanged":
        candidate = ORIGINAL
    elif kind == "prefix":
        candidate = CHANGED.replace("immutable header", "unapproved header")
    elif kind == "suffix":
        candidate = CHANGED.rstrip()
    else:
        validation = "synthetic marker error"
    install_artificial_diff_doubles(adapter, candidate=candidate, applied=applied, validation=validation)
    with pytest.raises(adapter["FixedProfileError"]):
        adapter["_candidate"](request, reply())
