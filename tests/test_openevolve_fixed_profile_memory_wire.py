"""Real Lunar memory wires reach only the fixed adapter's data projection.

The added adapter source is executed after removing its three upstream imports.
No upstream module, diff helper, broker request, evaluator or candidate is run.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot, load_memory_snapshot

_CONTRACT = "a" * 64
_CAUSAL_FIELDS = {"condition", "action", "observed_result", "applicability"}


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _item():
    return MemoryItem(
        memory_id="memory-original", problem_family="exact-integer",
        trigger="Legacy condition", strategy="Legacy action",
        expected_result="Legacy observation", failure_boundary="Legacy applicability",
        compatible_contracts=(_CONTRACT,), compatible_solvers=("openevolve",),
        verifier_outcome="pass", receipt_sha256="d" * 64,
        episode_id="episode-source", condition="Current condition",
        action="Current action", observed_result="Current observation",
        applicability="Current applicability",
    )


@pytest.fixture(params=["current", "legacy"])
def original_memory(request):
    """Produce both supported canonical wire generations using the real DTOs."""
    first = _item()
    foreign = replace(first, memory_id="memory-other-solver", compatible_solvers=("shinka",))
    snapshot = MemorySnapshot("snapshot-original", "e" * 64, (first, foreign))
    if request.param == "legacy":
        wire = snapshot.to_dict()
        for item in wire["items"]:
            for name in _CAUSAL_FIELDS:
                item.pop(name)
        # A loaded legacy record retains its original omitted extension fields.
        snapshot = MemorySnapshot.from_dict(wire)
    raw = snapshot.to_bytes()
    assert load_memory_snapshot(raw).to_bytes() == raw
    assert hashlib.sha256(raw).hexdigest() == snapshot.digest()
    return request.param, snapshot, raw


@pytest.fixture
def adapter_data_only():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools/openevolve_fixed_profile/assets/fixed_entrypoint.py"
    )
    tree = ast.parse(source.read_bytes())
    upstream = {
        "openevolve.lunar_fixed_broker", "openevolve.prompt.templates",
        "openevolve.utils.code_utils",
    }
    imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module in upstream
    ]
    assert len(imports) == 3 and {node.module for node in imports} == upstream
    tree.body = [node for node in tree.body if node not in imports]
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module is not None and node.module.startswith("openevolve")
        for node in ast.walk(tree)
    )
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        pytest.fail("memory projection must not call upstream helpers or the broker")

    namespace = {
        "__name__": "fixed_profile_memory_data_only", "__file__": str(source),
        "brokered_producer_post": forbidden, "extract_diffs": forbidden,
        "apply_diff_blocks": forbidden, "enforce_evolve_blocks": forbidden,
        "BASE_SYSTEM_TEMPLATE": "unused", "DIFF_USER_TEMPLATE": "unused",
    }
    exec(compile(tree, str(source), "exec"), namespace)  # noqa: S102
    yield namespace
    assert calls == []


def _request_bytes(memory_raw):
    return _canonical(SolverRequest.build(
        episode_id="episode-original", contract_sha256=_CONTRACT,
        evaluator_sha256="b" * 64, environment_sha256="c" * 64,
        memory_snapshot_sha256=hashlib.sha256(memory_raw).hexdigest(),
        solver_id="openevolve", solver_settings={
            "model": "fixture-model", "initial_program": "def solve(x):\n    return x + 0\n",
            "task": "Preserve the exact result.",
        }, budget={"deadline_unix": 2_000_000_000}, practice_charter={},
    ).to_dict())


def _projection(adapter, raw):
    request, memory = adapter["_inputs"](_request_bytes(raw), raw)
    return json.loads(adapter["_memory_history"](request, memory))


def test_real_current_and_legacy_memory_wires_preserve_causal_projection(
    adapter_data_only, original_memory,
):
    generation, _snapshot, raw = original_memory
    prefix = "Current" if generation == "current" else "Legacy"
    assert _projection(adapter_data_only, raw) == [{
        "condition": prefix + " condition", "action": prefix + " action",
        "observed_result": prefix + " observation",
        "applicability": prefix + " applicability",
    }]


@pytest.mark.parametrize("field,replacement", [
    ("snapshot_id", ""), ("snapshot_id", "bad\nidentity"),
    ("parent_snapshot_sha256", "g" * 64),
    ("parent_snapshot_sha256", 1),
])
def test_snapshot_format_is_validated_even_with_matching_original_bytes_digest(
    adapter_data_only, original_memory, field, replacement,
):
    wire = json.loads(original_memory[2])
    wire[field] = replacement
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


def test_snapshot_allows_original_root_parent_without_requiring_a_successor(
    adapter_data_only, original_memory,
):
    wire = json.loads(original_memory[2])
    wire["parent_snapshot_sha256"] = None
    assert len(_projection(adapter_data_only, _canonical(wire))) == 1


@pytest.mark.parametrize("mutation", ["snapshot-extra", "item-extra", "missing-trigger", "missing-receipt"])
def test_memory_fieldsets_match_the_real_dto_contract(
    adapter_data_only, original_memory, mutation,
):
    wire = json.loads(original_memory[2])
    if mutation == "snapshot-extra":
        wire["unexpected"] = "not part of the original memory schema"
    elif mutation == "item-extra":
        wire["items"][0]["unexpected"] = "not part of the original memory schema"
    else:
        wire["items"][0].pop("trigger" if mutation == "missing-trigger" else "receipt_sha256")
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


@pytest.mark.parametrize("field,replacement", [
    ("memory_id", "bad\ridentity"), ("episode_id", "bad\nidentity"),
    ("problem_family", ""), ("problem_family", "x" * 257),
    ("trigger", ""), ("strategy", "x" * 8193),
    ("expected_result", None), ("failure_boundary", False),
    ("receipt_sha256", "g" * 64), ("compatible_contracts", ["g" * 64]),
    ("compatible_solvers", ["bad\nsolver"]),
    ("status", "rejected"), ("verifier_outcome", "unresolved"),
    ("condition", None), ("action", ""),
])
def test_each_memory_field_is_checked_even_when_digest_matches_target_bytes(
    adapter_data_only, original_memory, field, replacement,
):
    wire = json.loads(original_memory[2])
    wire["items"][0][field] = replacement
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


def test_incompatible_memory_still_has_to_satisfy_the_original_item_schema(
    adapter_data_only, original_memory,
):
    wire = json.loads(original_memory[2])
    assert wire["items"][1]["compatible_solvers"] == ["shinka"]
    wire["items"][1]["receipt_sha256"] = "not-a-digest"
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


def test_prompt_prefix_limit_does_not_hide_invalid_later_memory(adapter_data_only):
    base = _item()
    snapshot = MemorySnapshot("snapshot-nine", None, tuple(
        replace(base, memory_id=f"memory-{ordinal}") for ordinal in range(9)
    ))
    assert len(_projection(adapter_data_only, snapshot.to_bytes())) == 8
    wire = snapshot.to_dict()
    wire["items"][-1]["receipt_sha256"] = "not-a-digest"
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


def test_duplicate_memory_identity_is_refused_after_fresh_valid_input(
    adapter_data_only, original_memory,
):
    wire = json.loads(original_memory[2])
    wire["items"][1]["memory_id"] = wire["items"][0]["memory_id"]
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        _projection(adapter_data_only, _canonical(wire))


def _artificial_candidate_orchestration(adapter, *, applied=1, protected=None):
    """Artificial doubles verify Lunar sequencing, never upstream diff semantics."""
    calls = []
    changed = "def solve(x):\n    return x\n"
    diffs = [("return x + 0", "return x")]
    adapter["DIFF_USER_TEMPLATE"] = (
        "{current_program}\n{improvement_areas}\n{evolution_history}"
    )

    def extract(content):
        calls.append(("extract", content))
        return diffs

    def apply(original, parsed):
        calls.append(("apply", original, parsed))
        return changed, applied

    def protect(original, proposed):
        calls.append(("protect", original, proposed))
        return original if protected == "unchanged" else proposed

    def post(request_id, body, *, deadline_ns):
        calls.append(("post", request_id, json.loads(body), deadline_ns))
        return 200, _canonical({"choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "artificial diff response"},
        }]})

    adapter.update(extract_diffs=extract, apply_diff_blocks=apply, enforce_evolve_blocks=protect)
    return calls, changed.encode(), post


def test_artificial_diff_doubles_cover_one_request_and_successful_candidate_orchestration(
    adapter_data_only, original_memory,
):
    calls, changed, post = _artificial_candidate_orchestration(adapter_data_only)
    now = 100
    adapter_data_only["time"] = SimpleNamespace(
        monotonic_ns=lambda: now, time=lambda: 1_900_000_000,
    )
    raw = original_memory[2]
    candidate, wrapper = adapter_data_only["propose"](
        _request_bytes(raw), raw, deadline_ns=200, post=post,
    )
    assert candidate == changed and wrapper == b'{"candidate_path":"candidate.py"}'
    assert [call[0] for call in calls] == ["post", "extract", "apply", "protect"]
    assert calls[0][1] == "req-1" and calls[0][3] == 200
    body = calls[0][2]
    assert body["model"] == "fixture-model"
    assert body["stream"] is False and body["n"] == 1 and body["temperature"] == 0
    assert "return x + 0" in body["messages"][1]["content"]


@pytest.mark.parametrize("refusal", ["unmatched", "unchanged"])
def test_artificial_diff_doubles_refuse_unapplied_or_protected_unchanged_candidate(
    adapter_data_only, original_memory, refusal,
):
    calls, _changed, post = _artificial_candidate_orchestration(
        adapter_data_only, applied=0 if refusal == "unmatched" else 1,
        protected="unchanged" if refusal == "unchanged" else None,
    )
    adapter_data_only["time"] = SimpleNamespace(
        monotonic_ns=lambda: 100, time=lambda: 1_900_000_000,
    )
    raw = original_memory[2]
    with pytest.raises(adapter_data_only["FixedProfileError"]):
        adapter_data_only["propose"](_request_bytes(raw), raw, deadline_ns=200, post=post)
    expected = ["post", "extract", "apply"]
    if refusal == "unchanged":
        expected.append("protect")
    assert [call[0] for call in calls] == expected


@pytest.mark.parametrize("expired_clock", ["monotonic", "unix"])
def test_reply_after_original_deadline_is_refused_before_any_diff_helper(
    adapter_data_only, original_memory, expired_clock,
):
    calls, _changed, post = _artificial_candidate_orchestration(adapter_data_only)
    clock = {"monotonic": 100, "unix": 1_900_000_000}
    adapter_data_only["time"] = SimpleNamespace(
        monotonic_ns=lambda: clock["monotonic"], time=lambda: clock["unix"],
    )

    def late_post(request_id, body, *, deadline_ns):
        reply = post(request_id, body, deadline_ns=deadline_ns)
        if expired_clock == "monotonic":
            clock["monotonic"] = deadline_ns
        else:
            clock["unix"] = 2_000_000_000
        return reply

    raw = original_memory[2]
    with pytest.raises(adapter_data_only["FixedProfileError"], match="deadline_expired"):
        adapter_data_only["propose"](
            _request_bytes(raw), raw, deadline_ns=200, post=late_post,
        )
    assert [call[0] for call in calls] == ["post"]


def _original_file_grants(tmp_path, memory_raw):
    attempt = tmp_path / "attempt"
    work = attempt / "work"
    inputs = attempt / ".rsi-input"
    output = attempt / "output"
    work.mkdir(parents=True)
    inputs.mkdir()
    output.mkdir()
    for name, raw in (("request.json", _request_bytes(memory_raw)), ("memory.json", memory_raw)):
        path = inputs / name
        path.write_bytes(raw)
        path.chmod(0o400)
    return work, output


@pytest.mark.parametrize("remaining_seconds", [10, 600])
def test_artificial_main_writes_candidate_before_create_only_wrapper_commit(
    adapter_data_only, original_memory, tmp_path, monkeypatch, remaining_seconds,
):
    calls, changed, post = _artificial_candidate_orchestration(adapter_data_only)
    work, output = _original_file_grants(tmp_path, original_memory[2])
    monkeypatch.chdir(work)
    # Preserve an earlier original deadline and independently enforce the local cap.
    adapter_data_only["time"] = SimpleNamespace(
        monotonic_ns=lambda: 100, time=lambda: 2_000_000_000 - remaining_seconds,
    )
    adapter_data_only["brokered_producer_post"] = post
    original_write = adapter_data_only["_write_at"]
    writes = []

    def observe_write(directory, name, raw):
        writes.append(name)
        if name == "result.json":
            assert (output / "candidate.py").read_bytes() == changed
            assert not (output / "result.json").exists()
        return original_write(directory, name, raw)

    adapter_data_only["_write_at"] = observe_write
    adapter_data_only["main"](["--lunar-rsi-input-v1", "f" * 64])
    assert writes == ["candidate.py", "result.json"]
    assert (output / "candidate.py").read_bytes() == changed
    assert (output / "result.json").read_bytes() == b'{"candidate_path":"candidate.py"}'
    assert (output / "candidate.py").stat().st_mode & 0o777 == 0o400
    assert (output / "result.json").stat().st_mode & 0o777 == 0o400
    assert [call[0] for call in calls] == ["post", "extract", "apply", "protect"]
    assert calls[0][3] == min(remaining_seconds, 60) * 1_000_000_000 + 100
    descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in ("candidate.py", "result.json"):
            with pytest.raises(FileExistsError):
                original_write(descriptor, name, b"must-not-overwrite")
    finally:
        os.close(descriptor)
    assert (output / "candidate.py").read_bytes() == changed
    assert (output / "result.json").read_bytes() == b'{"candidate_path":"candidate.py"}'


def test_wrapper_write_failure_retains_partial_candidate_without_a_completion_marker(
    adapter_data_only, original_memory, tmp_path, monkeypatch,
):
    _calls, changed, post = _artificial_candidate_orchestration(adapter_data_only)
    work, output = _original_file_grants(tmp_path, original_memory[2])
    monkeypatch.chdir(work)
    adapter_data_only["brokered_producer_post"] = post
    adapter_data_only["time"] = SimpleNamespace(
        monotonic_ns=lambda: 100, time=lambda: 1_999_999_990,
    )
    original_write = adapter_data_only["_write_at"]

    def fail_wrapper(directory, name, raw):
        if name == "result.json":
            raise OSError("artificial wrapper write failure")
        return original_write(directory, name, raw)

    adapter_data_only["_write_at"] = fail_wrapper
    with pytest.raises(OSError, match="artificial wrapper"):
        adapter_data_only["main"](["--lunar-rsi-input-v1", "f" * 64])
    assert (output / "candidate.py").read_bytes() == changed
    assert not (output / "result.json").exists()
