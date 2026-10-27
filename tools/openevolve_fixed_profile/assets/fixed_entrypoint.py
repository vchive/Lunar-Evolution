"""Source-only fixed single-candidate profile for OpenEvolve v0.4.0.

The native host must validate the original RSI marker/manifest, grant exactly the
two input files, and own the absolute deadline and broker request ledger. This
target consumes those files; it does not establish a runtime observation,
native generic envelope, evaluation result, or publication authority.

Profile settings live inside the existing original SolverRequest:
``model``, ``initial_program`` and ``task`` are the only supported keys. No
module, evaluator, command, template directory or provider is configurable.
Only the host-assigned anonymous-pipe descriptor environment is consulted by
the existing target broker helper. No endpoint or credential reaches here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import time

from openevolve.lunar_fixed_broker import brokered_producer_post
from openevolve.prompt.templates import BASE_SYSTEM_TEMPLATE, DIFF_USER_TEMPLATE
from openevolve.utils.code_utils import (
    apply_diff_blocks,
    enforce_evolve_blocks,
    extract_diffs,
)

PROFILE = "lunar-openevolve-v040-one-diff-source-v1"
MAX_RECORD_BYTES = 128 * 1024
MAX_PROGRAM_BYTES = 32 * 1024
MAX_TASK_BYTES = 8 * 1024
MAX_MEMORY_PROMPT_BYTES = 16 * 1024
MAX_PROMPT_BYTES = 64 * 1024
MAX_REPLY_BYTES = 64 * 1024
MAX_DIFFS = 16
MAX_LINES = 2048
MAX_ATTEMPT_SECONDS = 60
_REQUEST_FIELDS = {
    "schema_version", "kind", "episode_id", "contract_sha256",
    "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256",
    "solver_id", "solver_settings", "budget", "practice_charter",
}
_MEMORY_FIELDS = {
    "protocol", "schema_version", "snapshot_id", "parent_snapshot_sha256", "items",
}
_MEMORY_ITEM_REQUIRED = {
    "memory_id", "problem_family", "trigger", "strategy", "expected_result",
    "failure_boundary", "compatible_contracts", "compatible_solvers",
    "verifier_outcome", "receipt_sha256", "episode_id", "status",
}
_MEMORY_ITEM_OPTIONAL = {"condition", "action", "observed_result", "applicability"}
_HEX = re.compile(r"[0-9a-f]{64}")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")


class FixedProfileError(ValueError):
    """A bounded error code with no input, provider response or source prose."""


def _fail(code):
    raise FixedProfileError("openevolve_fixed_" + code)


def _canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail("json_invalid")


def _shape(value, depth=0, remaining=None):
    if remaining is None:
        remaining = [16384]
    remaining[0] -= 1
    if depth > 16 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is str:
        _text(value, MAX_RECORD_BYTES, empty=True)
        return
    if kind is int:
        if value.bit_length() > 256:
            _fail("shape_invalid")
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        if len(value) > 512 or any(type(key) is not str for key in value):
            _fail("shape_invalid")
        for key, item in value.items():
            _shape(key, depth + 1, remaining)
            _shape(item, depth + 1, remaining)
        return
    if kind is list:
        if len(value) > 512:
            _fail("shape_invalid")
        for item in value:
            _shape(item, depth + 1, remaining)
        return
    _fail("shape_invalid")


def _decode(raw, limit=MAX_RECORD_BYTES, canonical=True):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        _fail("json_invalid")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _fail("duplicate_key")
            value[key] = item
        return value

    def invalid(_value):
        _fail("json_invalid")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        _shape(result)
        if canonical and _canonical(result) != raw:
            _fail("noncanonical_json")
        return result
    except FixedProfileError:
        raise
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        _fail("json_invalid")


def _text(value, limit, empty=False):
    if type(value) is not str or (not empty and not value.strip()) or "\x00" in value:
        _fail("text_invalid")
    try:
        if len(value.encode("utf-8")) > limit:
            _fail("text_too_large")
    except UnicodeError:
        _fail("text_invalid")
    return value


def _digest(value):
    if type(value) is not str or _HEX.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _identifier(value):
    _text(value, 256)
    if "\n" in value or "\r" in value:
        _fail("identity_invalid")
    return value


def _memory_item(item):
    if (type(item) is not dict or not _MEMORY_ITEM_REQUIRED <= set(item)
            or set(item) - (_MEMORY_ITEM_REQUIRED | _MEMORY_ITEM_OPTIONAL)):
        _fail("memory_invalid")
    _identifier(item["memory_id"])
    _identifier(item["episode_id"])
    _text(item["problem_family"], 256)
    for name in ("trigger", "strategy", "expected_result", "failure_boundary"):
        _text(item[name], 8192)
    for name in _MEMORY_ITEM_OPTIONAL:
        if name in item:
            _text(item[name], 8192)
    _digest(item["receipt_sha256"])
    if item["status"] != "approved" or item["verifier_outcome"] != "pass":
        _fail("memory_unapproved")
    contracts, solvers = item["compatible_contracts"], item["compatible_solvers"]
    if (type(contracts) is not list or len(contracts) > 32
            or type(solvers) is not list or not 1 <= len(solvers) <= 32):
        _fail("memory_invalid")
    for digest in contracts:
        _digest(digest)
    for solver in solvers:
        _identifier(solver)
    return item


def _inputs(request_raw, memory_raw):
    request = _decode(request_raw)
    memory = _decode(memory_raw)
    if (type(request) is not dict or set(request) != _REQUEST_FIELDS
            or request["schema_version"] != "1" or request["kind"] != "rsi_solver_request"
            or request["solver_id"] != "openevolve"):
        _fail("request_invalid")
    for name in ("contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256"):
        _digest(request[name])
    _identifier(request["episode_id"])
    if (type(memory) is not dict or set(memory) != _MEMORY_FIELDS
            or memory["protocol"] != "lunar-rsi-learning-v1" or memory["schema_version"] != "1"
            or type(memory["items"]) is not list or len(memory["items"]) > 256
            or hashlib.sha256(memory_raw).hexdigest() != request["memory_snapshot_sha256"]):
        _fail("memory_pin_mismatch")
    _identifier(memory["snapshot_id"])
    if memory["parent_snapshot_sha256"] is not None:
        _digest(memory["parent_snapshot_sha256"])
    identifiers = set()
    for item in memory["items"]:
        _memory_item(item)
        if item["memory_id"] in identifiers:
            _fail("memory_invalid")
        identifiers.add(item["memory_id"])
    settings = request["solver_settings"]
    if type(settings) is not dict or set(settings) != {"model", "initial_program", "task"}:
        _fail("settings_invalid")
    if type(settings["model"]) is not str or _MODEL.fullmatch(settings["model"]) is None:
        _fail("model_invalid")
    program = _text(settings["initial_program"], MAX_PROGRAM_BYTES)
    _text(settings["task"], MAX_TASK_BYTES)
    if len(program.splitlines()) > MAX_LINES:
        _fail("program_too_many_lines")
    for name in ("budget", "practice_charter"):
        if (type(request[name]) is not dict or len(request[name]) > 32
                or any(not key for key in request[name])):
            _fail("request_invalid")
    deadline = request["budget"].get("deadline_unix")
    if (type(deadline) not in {int, float} or not math.isfinite(deadline)
            or deadline <= 0):
        _fail("deadline_invalid")
    return request, memory


def _memory_history(request, memory):
    """Render only approved compatible observations, as untrusted prompt context."""
    history = []
    identifiers = set()
    prefix_full = False
    for item in memory["items"]:
        _memory_item(item)
        identifier = item["memory_id"]
        if identifier in identifiers:
            _fail("memory_invalid")
        identifiers.add(identifier)
        contracts, solvers = item["compatible_contracts"], item["compatible_solvers"]
        rendered = {
            "condition": _text(item.get("condition", item.get("trigger")), 8192),
            "action": _text(item.get("action", item.get("strategy")), 8192),
            "observed_result": _text(item.get("observed_result", item.get("expected_result")), 8192),
            "applicability": _text(item.get("applicability", item.get("failure_boundary")), 8192),
        }
        if (prefix_full or "openevolve" not in solvers
                or (contracts and request["contract_sha256"] not in contracts)):
            continue
        # Deterministic original-order prefix: do not replace it with later items.
        proposed = history + [rendered]
        if len(proposed) > 8 or len(_canonical(proposed)) > MAX_MEMORY_PROMPT_BYTES:
            prefix_full = True
            continue
        history = proposed
    return _canonical(history).decode("utf-8")


def _body(request, memory):
    settings = request["solver_settings"]
    charter = _canonical(request["practice_charter"]).decode("utf-8")
    prompt = DIFF_USER_TEMPLATE.format(
        metrics="No authoritative local evaluation has run for this proposal.",
        improvement_areas=settings["task"], artifacts="Practice charter: " + charter,
        evolution_history=_memory_history(request, memory), language="python",
        current_program=settings["initial_program"],
    )
    _text(prompt, MAX_PROMPT_BYTES)
    return _canonical({
        "model": settings["model"], "stream": False,
        "temperature": 0, "max_tokens": 1024, "n": 1,
        "messages": [
            {"role": "system", "content": BASE_SYSTEM_TEMPLATE},
            {"role": "user", "content": prompt},
        ],
    })


def _candidate(request, reply):
    value = _decode(reply, limit=MAX_REPLY_BYTES, canonical=False)
    if (type(value) is not dict or type(value.get("choices")) is not list
            or len(value["choices"]) != 1 or type(value["choices"][0]) is not dict):
        _fail("reply_invalid")
    choice = value["choices"][0]
    message = choice.get("message")
    if (choice.get("finish_reason") != "stop" or type(message) is not dict
            or message.get("role") != "assistant" or message.get("tool_calls")
            or message.get("function_call") or message.get("refusal")):
        _fail("reply_invalid")
    content = _text(message.get("content"), MAX_REPLY_BYTES)
    try:
        diffs = extract_diffs(content)
        if not 1 <= len(diffs) <= MAX_DIFFS or any(not search.strip() for search, _ in diffs):
            _fail("diff_invalid")
        original = request["solver_settings"]["initial_program"]
        changed, applied = apply_diff_blocks(original, diffs)
        if applied != len(diffs):
            _fail("diff_unmatched")
        candidate = enforce_evolve_blocks(original, changed)
    except FixedProfileError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError):
        _fail("diff_invalid")
    _text(candidate, MAX_PROGRAM_BYTES)
    if candidate == original:
        _fail("candidate_unchanged")
    if len(candidate.splitlines()) > MAX_LINES:
        _fail("program_too_many_lines")
    return candidate.encode("utf-8")


def propose(request_raw, memory_raw, *, deadline_ns, post=brokered_producer_post):
    """Consume original grants and make exactly one brokered candidate proposal.

    ``post`` is an internal test seam, never deserialized from request input. The
    executable entrypoint below always uses the fixed existing protocol client.
    The host broker remains the request-count and terminal-journal authority.
    """
    request, memory = _inputs(request_raw, memory_raw)
    if type(deadline_ns) is not int or time.monotonic_ns() >= deadline_ns:
        _fail("deadline_expired")
    if time.time() >= request["budget"]["deadline_unix"]:
        _fail("deadline_expired")
    body = _body(request, memory)
    status, reply = post("req-1", body, deadline_ns=deadline_ns)
    if type(status) is not int or status != 200:
        _fail("http_failed")
    if time.monotonic_ns() >= deadline_ns or time.time() >= request["budget"]["deadline_unix"]:
        _fail("deadline_expired")
    candidate = _candidate(request, reply)
    return candidate, _canonical({"candidate_path": "candidate.py"})


def _read_at(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o400 or not 0 < before.st_size <= MAX_RECORD_BYTES):
            _fail("grant_invalid")
        chunks = []
        remaining = MAX_RECORD_BYTES + 1
        while remaining:
            part = os.read(descriptor, min(65536, remaining))
            if not part:
                break
            remaining -= len(part)
            chunks.append(part)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(raw) != before.st_size
                or any(getattr(before, field) != getattr(after, field) for field in fields)
                or any(getattr(after, field) != getattr(named, field) for field in fields)):
            _fail("grant_drift")
        return raw
    finally:
        os.close(descriptor)


def _write_at(directory, name, raw):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=directory)
    try:
        os.fchmod(descriptor, 0o400)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                _fail("output_failed")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv=None):
    """Fixed source entrypoint; host validation owns marker-to-grant binding."""
    argv = sys.argv[1:] if argv is None else argv
    if (type(argv) is not list or len(argv) != 2 or argv[0] != "--lunar-rsi-input-v1"
            or type(argv[1]) is not str or _HEX.fullmatch(argv[1]) is None):
        _fail("argv_invalid")
    parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        inputs = os.open(".rsi-input", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            request_raw = _read_at(inputs, "request.json")
            memory_raw = _read_at(inputs, "memory.json")
        finally:
            os.close(inputs)
        request, _memory = _inputs(request_raw, memory_raw)
        remaining = request["budget"]["deadline_unix"] - time.time()
        if remaining <= 0:
            _fail("deadline_expired")
        # This fixed profile adds a stricter local cap; the native owner
        # still enforces any earlier parent/launch deadline independently.
        deadline_ns = time.monotonic_ns() + int(min(remaining, MAX_ATTEMPT_SECONDS) * 1_000_000_000)
        candidate, wrapper = propose(
            request_raw, memory_raw, deadline_ns=deadline_ns,
            post=brokered_producer_post,
        )
        if time.monotonic_ns() >= deadline_ns or time.time() >= request["budget"]["deadline_unix"]:
            _fail("deadline_expired")
        output = os.open("output", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            _write_at(output, "candidate.py", candidate)
            # Wrapper is committed last. Partial output never signals completion.
            _write_at(output, "result.json", wrapper)
            os.fsync(output)
        finally:
            os.close(output)
    finally:
        os.close(parent)


if __name__ == "__main__":
    main()

