"""Original local file/pipe facts with artificial diff and broker fixtures only.

No upstream solver helper, model, evaluator, candidate, CPython build or sealed
runtime is executed. Preparing source or calling this fragment is not a native
original-attempt acquisition, accepted runtime or production admission.
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import re
import select
import stat
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from lunar_evolution.producer_handoff import ProducerResultEnvelope
from lunar_evolution.static_python_producer_completion import FixedProducerCompletionBinding
from lunar_evolution.static_python_producer_envelope_completion import (
    compare_fixed_producer_envelope_completion,
)
from tools.static_python_rsi_fixture import envelope_source as source
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_sink_launcher

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = "# EVOLVE-BLOCK-START\ndef solve(x):\n    return x + 0\n# EVOLVE-BLOCK-END\n"
CHANGED = ORIGINAL.replace("return x + 0", "return x")
DIFF = "<<<<<<< SEARCH\nreturn x + 0\n=======\nreturn x\n>>>>>>> REPLACE"


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _blob(raw):
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _sources(solver, **overrides):
    arguments = {
        "frozen_names": tuple(sorted(("_lunar_static_main", solver, solver + ".lunar_fixed"))),
        "builtin_names": ("_imp", "builtins", "sys"), "aliases": (),
        "frozen_packages": (solver,), "profile": source.FIXED_PRODUCER_ENVELOPE_PROFILE,
    }
    arguments.update(overrides)
    return source.prepare_fixed_producer_envelope_sources(solver, **arguments)


class _PipeOS:
    """Map logical FD197 to an owned real pipe without overwriting pytest FDs."""

    def __init__(self, writer):
        self.writer, self.closed = writer, False
        self.writes, self.syncs, self.final_sync_failure = [], [], False
        self.corrupt_output = False

    def __getattr__(self, name):
        return getattr(os, name)

    def descriptor(self, descriptor):
        return self.writer if descriptor == 197 else descriptor

    def fstat(self, descriptor):
        return os.fstat(self.descriptor(descriptor))

    def close(self, descriptor):
        if descriptor == 197:
            self.closed = True
        return os.close(self.descriptor(descriptor))

    def write(self, descriptor, raw):
        self.writes.append((descriptor, bytes(raw)))
        if descriptor != 197 and self.corrupt_output:
            raw = bytes([raw[0] ^ 1]) + raw[1:]
        return os.write(self.descriptor(descriptor), raw)

    def fsync(self, descriptor):
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        self.syncs.append(directory)
        if self.final_sync_failure and directory:
            raise OSError("inert final directory sync failure")
        return os.fsync(descriptor)


def _namespace(solver, prepared):
    # Remove every upstream import and supply explicitly artificial fixtures.
    tree = ast.parse(prepared.producer_source)
    imports = [node for node in tree.body
               if isinstance(node, ast.ImportFrom) and node.module.startswith(solver + ".")]
    assert len(imports) == (3 if solver == "openevolve" else 4)
    tree.body = [node for node in tree.body if node not in imports]
    values = {
        "__name__": "local_completion_source_fixture",
        "BASE_SYSTEM_TEMPLATE": "artificial system",
        "DIFF_USER_TEMPLATE": "{current_program}\n{improvement_areas}\n{evolution_history}",
        "DIFF_SYS_FORMAT": "artificial system",
        "DIFF_ITER_MSG": "{language}\n{code_content}\n{performance_metrics}\n{text_feedback_section}",
        "PATCH_PATTERN": re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.DOTALL),
        "PatchError": ValueError,
        "extract_diffs": lambda _content: [("return x + 0", "return x")],
        "apply_diff_blocks": lambda _original, _diffs: (CHANGED, 1),
        "enforce_evolve_blocks": lambda _original, proposed: proposed,
        "apply_search_replace": lambda *_args, **_kwargs: (CHANGED, 1),
        "validate_evolve_markers": lambda *_args: None,
        "brokered_producer_post": lambda *_args, **_kwargs: (503, b"{}"),
    }
    exec(compile(tree, "reviewed_completion_source", "exec"), values)  # noqa: S102
    return values


@pytest.fixture(params=("openevolve", "shinka"))
def local_attempt(request, tmp_path, monkeypatch):
    solver = request.param
    prepared = _sources(solver)
    namespace = _namespace(solver, prepared)
    memory = {"protocol": "lunar-rsi-learning-v1", "schema_version": "1",
              "snapshot_id": "original", "parent_snapshot_sha256": None, "items": []}
    memory_raw = _canonical(memory)
    original = {
        "schema_version": "1", "kind": "rsi_solver_request", "episode_id": "original",
        "contract_sha256": "a" * 64, "evaluator_sha256": "b" * 64,
        "environment_sha256": "c" * 64, "memory_snapshot_sha256": _blob(memory_raw)["sha256"],
        "solver_id": solver, "solver_settings": {
            "model": "fixture-model", "initial_program": ORIGINAL, "task": "Remove redundant work.",
        }, "budget": {"deadline_unix": time.time() + 30}, "practice_charter": {},
    }
    request_raw = _canonical(original)
    (tmp_path / "work").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / ".rsi-input").mkdir()
    for name, raw in (("request.json", request_raw), ("memory.json", memory_raw)):
        path = tmp_path / ".rsi-input" / name
        path.write_bytes(raw)
        path.chmod(0o400)
    reader, writer = os.pipe()
    os.set_blocking(writer, False)
    mapped = _PipeOS(writer)
    namespace["os"] = mapped
    namespace["_lunar_completion_fcntl"] = SimpleNamespace(
        F_GETFL=fcntl.F_GETFL,
        fcntl=lambda descriptor, operation: fcntl.fcntl(mapped.descriptor(descriptor), operation),
    )

    class Poll:
        def __init__(self):
            self.actual = select.poll()

        def register(self, descriptor, events):
            self.actual.register(mapped.descriptor(descriptor), events)

        def poll(self, timeout):
            return self.actual.poll(timeout)

    namespace["_lunar_completion_select"] = SimpleNamespace(poll=Poll, POLLOUT=select.POLLOUT)
    reply = _canonical({"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": DIFF,
    }}]})
    calls = []

    def post(request_id, body, *, deadline_ns):
        calls.append((request_id, body, deadline_ns))
        return 200, reply

    namespace["brokered_producer_post"] = post
    monkeypatch.chdir(tmp_path / "work")
    attempt = SimpleNamespace(
        solver=solver, namespace=namespace, mapped=mapped, reader=reader, root=tmp_path,
        request=request_raw, memory=memory_raw, reply=reply, calls=calls,
        deadline=time.monotonic_ns() + 5 * 10 ** 9,
    )
    try:
        yield attempt
    finally:
        if not mapped.closed:
            os.close(writer)
        os.close(reader)


def _records(attempt):
    raw = os.read(attempt.reader, source.MAX_FIXED_PRODUCER_ENVELOPE_COMPLETION_BYTES + 1)
    assert len(raw) <= source.MAX_FIXED_PRODUCER_ENVELOPE_COMPLETION_BYTES
    return raw, [json.loads(line) for line in raw.splitlines()]


def _run(attempt, manifest, deadline, run_id="original-run", producer_fingerprint="f" * 64):
    # Simulate the C launcher's sole writer ownership. Python only borrows it.
    try:
        return attempt.namespace["_lunar_envelope_main"](manifest, deadline, run_id, producer_fingerprint)
    finally:
        attempt.mapped.close(197)


def test_completion_path_records_actual_read_exchange_and_committed_bytes(local_attempt):
    item = local_attempt
    _run(item, "e" * 64, item.deadline)
    raw, records = _records(item)
    assert [record["phase"] for record in records] == ["begun", "committed"]
    assert [record["seq"] for record in records] == [0, 1]
    for record in records:
        assert record["deadline_monotonic_ns"] == item.deadline
        assert record["target_pid"] == os.getpid()
        assert record["manifest_sha256"] == "e" * 64
        assert record["solver"] == item.solver
    assert raw == b"".join(_canonical(record) + b"\n" for record in records)
    final = records[1]
    assert final["request"] == _blob(item.request) and final["memory"] == _blob(item.memory)
    assert len(item.calls) == 1 and item.calls[0][0] == "req-1"
    assert item.calls[0][2] <= item.deadline
    assert final["broker"] == {
        "request_id": "req-1", "request_count": 1, "status": 200,
        "request_body": _blob(item.calls[0][1]), "reply": _blob(item.reply),
    }
    expected_paths = ("candidate.py", "result.json") if item.solver == "openevolve" else (
        "gen_0/main.py", "programs.sqlite",
    )
    assert [entry["path"] for entry in final["artifacts"]] == list(expected_paths)
    assert final["artifacts"] == [dict(path=path, **_blob((item.root / "output" / path).read_bytes()))
                                  for path in expected_paths]
    compared = compare_fixed_producer_envelope_completion(
        raw, binding=FixedProducerCompletionBinding(item.solver, os.getpid(), "e" * 64, item.deadline),
        request_bytes=item.request, memory_bytes=item.memory,
        request_body_bytes=item.calls[0][1], reply_bytes=item.reply,
        artifacts=tuple((path, (item.root / "output" / path).read_bytes()) for path in expected_paths),
        envelope_bytes=(item.root / "output" / "producer-result.json").read_bytes(),
    )
    assert compared.canonical_bytes == raw
    assert not compared.original_acquisition_verified
    assert not compared.production_admission and not compared.online_publication
    assert (item.root / "output" / expected_paths[0]).read_bytes() == CHANGED.encode()
    envelope_raw = (item.root / "output" / "producer-result.json").read_bytes()
    envelope = ProducerResultEnvelope.from_dict(json.loads(envelope_raw))
    assert envelope.producer_id == item.solver
    assert envelope.producer_run_id == "original-run"  # Deliberately differs from episode_id.
    assert envelope.producer_fingerprint == "f" * 64
    assert envelope.contract_sha256 == "a" * 64
    assert envelope.status == "completed" and envelope.budget == {"requests": 1}
    assert envelope.materials[0].path == expected_paths[0] and len(envelope.materials) == 1
    assert envelope.materials[0].lineage == ()
    assert envelope.materials[0].sha256 == _blob(CHANGED.encode())["sha256"]
    assert envelope.external_evidence == {"present": False, "score_present": False, "payload_sha256": None}
    assert envelope_raw == _canonical(envelope.to_dict())
    if item.solver == "shinka":
        proposal = {"correct": False, "generation": 0, "program_id": "proposal"}
        assert envelope.materials[0].external_evidence == {
            "present": True, "score_present": False,
            "payload_sha256": _blob(_canonical(proposal))["sha256"],
        }
    else:
        assert envelope.materials[0].external_evidence == envelope.external_evidence
    assert final["envelope"] == dict(path="producer-result.json", **_blob(envelope_raw))
    assert (item.root / "output" / "producer-result.json").stat().st_mode & 0o777 == 0o400
    assert item.mapped.closed and item.mapped.syncs[-1] is True
    assert set(final) == {"protocol", "profile", "solver", "manifest_sha256", "target_pid",
                          "deadline_monotonic_ns", "seq", "phase", "request", "memory", "broker", "artifacts", "envelope"}


@pytest.mark.parametrize("failure", ("http", "bad-input", "final-sync", "existing-final", "expired-reply", "readback",
                                  "existing-envelope", "envelope-symlink"))
def test_partial_and_failed_attempts_never_emit_committed(local_attempt, failure):
    item = local_attempt
    if failure == "http":
        item.namespace["brokered_producer_post"] = lambda *_args, **_kwargs: (503, b"{}")
    elif failure == "bad-input":
        path = item.root / ".rsi-input" / "memory.json"
        path.chmod(0o600)
        path.write_bytes(b"{}")
        path.chmod(0o400)
    elif failure == "final-sync":
        item.mapped.final_sync_failure = True
    elif failure == "existing-final":
        name = "result.json" if item.solver == "openevolve" else "programs.sqlite"
        (item.root / "output" / name).write_bytes(b"existing")
    elif failure in {"existing-envelope", "envelope-symlink"}:
        path = item.root / "output" / "producer-result.json"
        if failure == "existing-envelope":
            path.write_bytes(b"existing")
        else:
            destination = item.root / "unmodified.txt"
            destination.write_bytes(b"original")
            path.symlink_to(destination)
    elif failure == "readback":
        item.mapped.corrupt_output = True
    else:
        original_post = item.namespace["brokered_producer_post"]
        clock = {"monotonic": time.monotonic_ns()}
        item.namespace["time"] = SimpleNamespace(monotonic_ns=lambda: clock["monotonic"], time=time.time)

        def late_reply(*args, **kwargs):
            response = original_post(*args, **kwargs)
            clock["monotonic"] = item.deadline
            return response

        item.namespace["brokered_producer_post"] = late_reply
    with pytest.raises((RuntimeError, ValueError, OSError)):
        _run(item, "e" * 64, item.deadline)
    _raw, records = _records(item)
    assert [record["phase"] for record in records] == ["begun"]
    assert item.mapped.closed


@pytest.mark.parametrize("bad", (True, 0, -1, 2 ** 64, "future"))
def test_invalid_original_deadline_refuses_before_any_read_or_broker(local_attempt, bad):
    item = local_attempt
    with pytest.raises(RuntimeError, match="envelope_deadline"):
        _run(item, "e" * 64, bad)
    assert item.calls == [] and item.mapped.writes == []


@pytest.mark.parametrize("profile", (None, False, "fixed-live-runtime-private-sink-v1", "unknown"))
def test_source_preparation_is_explicitly_default_off(profile):
    with pytest.raises(source.FixedProducerEnvelopeSourceError, match="source_profile"):
        _sources("openevolve", profile=profile)


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_composer_preserves_original_source_bytes_and_old_launcher(solver):
    original = (ROOT / "tools" / (solver + "_fixed_profile") / "assets/fixed_entrypoint.py").read_bytes()
    before = prepare_fixed_live_sink_launcher()
    prepared = _sources(solver)
    assert prepared.producer_source.startswith(original + b"\n")
    assert prepared == _sources(solver)
    assert prepare_fixed_live_sink_launcher() == before
    assert b"COMPLETION_FD" not in before
    assert prepared.launcher_source.index(b"close(LIVE_SINK_FD)) failed") < prepared.launcher_source.index(
        b'PyObject_GetAttrString(module, "_rsi_launch")',
    )
    assert b"PyLong_FromUnsignedLongLong(completion_deadline)" in prepared.launcher_source
    ast.parse(prepared.producer_source)
    ast.parse(prepared.frozen_main_source)


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_frozen_wrapper_forwards_exact_deadline_only_to_new_callable(monkeypatch, solver):
    prepared = _sources(solver)
    namespace = {}
    exec(compile(prepared.frozen_main_source, "reviewed_frozen_completion", "exec"), namespace)  # noqa: S102
    package, module = ModuleType(solver), ModuleType(solver + ".lunar_fixed")
    calls = []
    module._lunar_envelope_main = lambda *arguments: calls.append(arguments)
    monkeypatch.setitem(__import__("sys").modules, solver, package)
    monkeypatch.setitem(__import__("sys").modules, solver + ".lunar_fixed", module)
    namespace["_rsi_launch"]("e" * 64, 123456789, "original-run", "f" * 64)
    assert calls == [("e" * 64, 123456789, "original-run", "f" * 64)]
    with pytest.raises(ValueError):
        namespace["_rsi_launch"]("e" * 64, True, "original-run", "f" * 64)
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ("mutation", "symlink"))
def test_pinned_fragment_drift_refuses_before_preparation(tmp_path, monkeypatch, kind):
    for relative in source._PINS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    fragment = tmp_path / "tools/static_python_rsi_fixture/assets/fixed_producer_envelope.py"
    if kind == "mutation":
        fragment.write_bytes(fragment.read_bytes() + b"\n")
    else:
        target = tmp_path / "replacement.py"
        target.write_bytes(fragment.read_bytes())
        fragment.unlink()
        fragment.symlink_to(target)
    monkeypatch.setattr(source, "_ROOT", tmp_path)
    with pytest.raises(source.FixedProducerEnvelopeSourceError, match="source_pin"):
        _sources("openevolve")


@pytest.mark.parametrize("field,bad", [
    ("run_id", ""), ("run_id", "../run"), ("run_id", "password=hidden"),
    ("run_id", "x" * 129), ("run_id", True), ("run_id", "日本語"),
    ("producer_fingerprint", "F" * 64), ("producer_fingerprint", "f" * 63),
    ("producer_fingerprint", True),
])
def test_target_refuses_invalid_launch_fields_before_input_or_broker(local_attempt, field, bad):
    item = local_attempt
    with pytest.raises(RuntimeError, match="envelope_input"):
        _run(item, "e" * 64, item.deadline, **{field: bad})
    assert item.calls == [] and item.mapped.writes == []
    assert not (item.root / "output" / "producer-result.json").exists()


def test_envelope_is_create_only_and_fsyncs_before_committed(local_attempt):
    item = local_attempt
    events = []
    original_open = os.open
    original_fsync = item.mapped.fsync
    original_write = item.mapped.write
    original_read = os.read
    envelope_descriptors = set()

    def opened(name, flags, *args, **kwargs):
        descriptor = original_open(name, flags, *args, **kwargs)
        if name == "producer-result.json":
            events.append("envelope-create" if flags & os.O_WRONLY else "envelope-open-read")
            if flags & os.O_WRONLY:
                assert flags & os.O_EXCL and flags & os.O_NOFOLLOW
            envelope_descriptors.add(descriptor)
        return descriptor

    def synced(descriptor):
        events.append("directory-sync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file-sync")
        return original_fsync(descriptor)

    def written(descriptor, raw):
        if descriptor == 197:
            events.append(json.loads(raw)["phase"])
        return original_write(descriptor, raw)

    def read(descriptor, count):
        if descriptor in envelope_descriptors:
            events.append("envelope-readback")
        return original_read(descriptor, count)

    item.mapped.open, item.mapped.fsync, item.mapped.write, item.mapped.read = opened, synced, written, read
    _run(item, "e" * 64, item.deadline)
    _raw, records = _records(item)
    assert records[1]["phase"] == "committed"
    created = events.index("envelope-create")
    readback = events.index("envelope-readback", created)
    assert created < events.index("file-sync", created) < readback
    assert readback < events.index("directory-sync", readback) < events.index("committed")


@pytest.mark.parametrize("failure", ["fsync", "readback", "partial-write"])
def test_envelope_specific_failure_never_emits_committed(local_attempt, failure):
    item = local_attempt
    original_open, original_write = os.open, item.mapped.write
    original_fsync = item.mapped.fsync
    envelope_writer = {"descriptor": None, "writes": 0}

    def opened(name, flags, *args, **kwargs):
        descriptor = original_open(name, flags, *args, **kwargs)
        if name == "producer-result.json" and flags & os.O_WRONLY:
            envelope_writer["descriptor"] = descriptor
        return descriptor

    def written(descriptor, raw):
        if descriptor == envelope_writer["descriptor"]:
            if failure == "readback":
                raw = b"!" + raw[1:]
            elif failure == "partial-write":
                envelope_writer["writes"] += 1
                if envelope_writer["writes"] > 1:
                    raise OSError("inert partial envelope write")
                raw = raw[:7]
        return original_write(descriptor, raw)

    def synced(descriptor):
        if descriptor == envelope_writer["descriptor"] and failure == "fsync":
            raise OSError("inert envelope sync failure")
        return original_fsync(descriptor)

    item.mapped.open, item.mapped.write, item.mapped.fsync = opened, written, synced
    with pytest.raises((OSError, RuntimeError)):
        _run(item, "e" * 64, item.deadline)
    _raw, records = _records(item)
    assert [record["phase"] for record in records] == ["begun"]
    assert len(item.calls) == 1
