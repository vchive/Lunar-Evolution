"""Diagnostic contracts use fake frames/clocks/threads, never a live case."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "python_own_stack_diagnostic",
    Path(__file__).resolve().parents[1] / "tools/python_own_stack_diagnostic.py",
)
assert _SPEC and _SPEC.loader
diagnostic = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(diagnostic)


@pytest.fixture
def world(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=0.0)

    class Event:
        def __init__(self):
            self.flag = False
            self.advance = True
            self.waits = 0
            self.stop_after = None

        def set(self):
            self.flag = True

        def is_set(self):
            return self.flag

        def wait(self, interval):
            self.waits += 1
            if self.advance:
                clock.now += interval
            if self.stop_after == self.waits:
                self.flag = True
            return self.flag

    class Thread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            self.target = target
            self.ident = 202
            self.alive = False
            self.started = False
            self.joins = []

        def start(self):
            self.started = True

        def join(self, *, timeout):
            self.joins.append(timeout)

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(diagnostic, "threading", SimpleNamespace(
        Event=Event, Thread=Thread, get_ident=lambda: 101,
    ))
    monkeypatch.setattr(diagnostic, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(diagnostic, "_CURRENT_FRAMES", dict)
    # Keep test I/O injection local to the tool, without changing process-wide os.
    monkeypatch.setattr(diagnostic, "os", SimpleNamespace(**{
        name: getattr(os, name) for name in (
            "open", "close", "write", "fchmod", "fsync", "O_WRONLY", "O_CREAT",
            "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW",
        )
    }))
    output = tmp_path / "stacks.jsonl"

    def create(**kwargs):
        return diagnostic.StackSampler("/source", ["allowed.py"], output,
                                       stdlib_root="/stdlib", seconds=1.0, **kwargs)

    return SimpleNamespace(clock=clock, create=create, output=output)


def _records(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def _finish_run(sampler):
    sampler.start()
    sampler._run()
    return sampler.finish()


def _frame(filename="/source/allowed.py", function="approved", line=12, back=None):
    class Frame:
        def __init__(self):
            self.f_code = SimpleNamespace(co_filename=filename, co_name=function)
            self.f_lineno = line
            self.f_back = back

        def __getattribute__(self, name):
            if name in {"f_locals", "f_globals", "f_builtins", "f_trace"}:
                raise AssertionError("private frame metadata accessed")
            return object.__getattribute__(self, name)

    return Frame()


def test_duration_terminal_uses_observed_count_and_is_not_sample_limit(world):
    sampler = world.create()
    outcome = _finish_run(sampler)
    records = _records(world.output)
    assert [record["event"] for record in records] == ["start", "sample", "sample", "stop"]
    assert records[-1] == {
        "event": "stop", "reason": "duration_limit", "monotonic_seconds": 1.0,
        "samples_observed": 2, "samples_written": 2,
    }
    assert outcome == {"writer_running": False, "terminal_status": "written",
                       "reason": "duration_limit", "samples_observed": 2, "samples_written": 2}
    assert stat.S_IMODE(world.output.stat().st_mode) == 0o600
    assert sampler.thread.joins == [0.5]


def test_sample_limit_is_only_recorded_after_actual_full_exhaustion(world):
    sampler = world.create()
    sampler.stop.advance = False
    outcome = _finish_run(sampler)
    assert outcome["reason"] == "sample_limit"
    assert outcome["samples_written"] == sampler.max_samples == 3
    assert _records(world.output)[-1]["samples_written"] == 3


@pytest.mark.parametrize("waits,count", [(0, 0), (1, 1)])
def test_main_completion_is_distinct_from_bounds(world, waits, count):
    sampler = world.create()
    if not waits:
        sampler.stop.set()
    else:
        sampler.stop.stop_after = waits
    outcome = _finish_run(sampler)
    assert outcome["reason"] == "main_completed"
    assert outcome["samples_written"] == count
    assert _records(world.output)[-1]["reason"] == "main_completed"


@pytest.mark.parametrize("error,reason", [
    (TypeError, "observation_error"), (AttributeError, "observation_error"),
    (RuntimeError, "observation_error"), (ValueError, "observation_error"),
    (KeyboardInterrupt, "sampler_interrupted"), (SystemExit, "sampler_interrupted"),
])
def test_unexpected_observation_exit_cannot_misreport_sample_limit(world, monkeypatch, error, reason):
    sampler = world.create()
    calls = 0

    def frames():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error("private path argv key value must never appear")
        return {}

    monkeypatch.setattr(diagnostic, "_CURRENT_FRAMES", frames)
    outcome = _finish_run(sampler)
    assert outcome["reason"] == reason
    assert outcome["samples_observed"] == outcome["samples_written"] == 1
    assert outcome["terminal_status"] == "written"
    assert _records(world.output)[-1]["reason"] == reason
    assert b"private" not in world.output.read_bytes()


def test_wait_failure_is_not_attributed_to_a_sample_or_write(world, monkeypatch):
    sampler = world.create()

    def failed_wait(_interval):
        raise TypeError("unretained details")

    monkeypatch.setattr(sampler.stop, "wait", failed_wait)
    outcome = _finish_run(sampler)
    assert outcome["reason"] == "sampler_error"
    assert outcome["samples_written"] == 1


def test_partial_write_preserves_bytes_without_claiming_parseable_terminal(world, monkeypatch):
    sampler = world.create()
    write = diagnostic.os.write
    calls = 0

    def interrupted_write(fd, raw):
        nonlocal calls
        calls += 1
        if calls == 1:
            return write(fd, raw[:10])
        raise OSError("private filesystem details")

    monkeypatch.setattr(diagnostic.os, "write", interrupted_write)
    outcome = _finish_run(sampler)
    assert outcome == {"writer_running": False, "terminal_status": "write_unknown",
                       "reason": "output_error", "samples_observed": 1, "samples_written": 0}
    raw = world.output.read_bytes()
    assert len(raw) == sampler.bytes_written
    assert raw.endswith(b'{"event":"')
    assert b"stop" not in raw and b"private" not in raw
    assert sampler.fd is None


def test_terminal_write_failure_is_explicit_and_closes_writer(world, monkeypatch):
    sampler = world.create()
    sampler.stop.set()
    fd = sampler.fd

    def failed_write(_fd, _raw):
        raise OSError("unretained terminal failure")

    monkeypatch.setattr(diagnostic.os, "write", failed_write)
    outcome = _finish_run(sampler)
    assert outcome["reason"] == "main_completed"
    assert outcome["terminal_status"] == "write_unknown"
    assert [record["event"] for record in _records(world.output)] == ["start"]
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize("kind", ["record", "total"])
def test_output_caps_leave_reserved_terminal_room(world, monkeypatch, kind):
    sampler = world.create()
    if kind == "record":
        monkeypatch.setattr(sampler, "_sample", lambda _index: {
            "event": "sample", "padding": "x" * diagnostic._MAX_RECORD_BYTES,
        })
    else:
        monkeypatch.setattr(diagnostic, "_MAX_TOTAL_BYTES",
                            sampler.bytes_written + diagnostic._RESERVED_END_BYTES + 1)
    outcome = _finish_run(sampler)
    assert outcome["reason"] == kind + "_byte_limit"
    assert outcome["samples_observed"] == 1 and outcome["samples_written"] == 0
    assert outcome["terminal_status"] == "written"
    assert [record["event"] for record in _records(world.output)] == ["start", "stop"]
    assert world.output.stat().st_size <= diagnostic._MAX_TOTAL_BYTES


def test_finish_reports_live_writer_unknown_without_closing_its_fd(world):
    sampler = world.create()
    sampler.start()
    sampler.thread.alive = True
    fd = sampler.fd
    outcome = sampler.finish()
    assert outcome == {"writer_running": True, "terminal_status": "unknown",
                       "reason": "writer_running", "samples_observed": 0, "samples_written": 0}
    assert sampler.fd == fd
    os.fstat(fd)
    assert sampler.thread.joins == [0.5]
    assert [record["event"] for record in _records(world.output)] == ["start"]
    sampler._run()  # Synthetic writer now sees the already-set stop Event.
    sampler.thread.alive = False
    assert sampler.finish()["terminal_status"] == "written"
    assert _records(world.output)[-1]["reason"] == "main_completed"


def test_finish_before_start_closes_cleanly_and_cannot_be_restarted(world):
    sampler = world.create()
    assert sampler.finish()["reason"] == "not_started"
    assert sampler.fd is None
    with pytest.raises(diagnostic.DiagnosticError, match="^state_invalid$"):
        sampler.start()


def test_start_failure_has_fixed_reason_and_finish_remains_safe(world, monkeypatch):
    sampler = world.create()

    def fail():
        raise RuntimeError("private start detail")

    monkeypatch.setattr(sampler.thread, "start", fail)
    with pytest.raises(diagnostic.DiagnosticError, match="^start_failed$"):
        sampler.start()
    assert sampler.finish()["reason"] == "start_error"
    assert _records(world.output)[-1]["reason"] == "start_error"


@pytest.mark.parametrize("kind", ["fchmod", "write"])
def test_initialization_failure_closes_fd_and_keeps_partial_output(world, monkeypatch, kind):
    opened = []
    original_open = diagnostic.os.open

    def opening(*args):
        fd = original_open(*args)
        opened.append(fd)
        return fd

    def fail(*_args):
        raise OSError("private setup detail")

    monkeypatch.setattr(diagnostic.os, "open", opening)
    monkeypatch.setattr(diagnostic.os, kind, fail)
    with pytest.raises(diagnostic.DiagnosticError, match="^initialization_failed$"):
        world.create()
    assert len(opened) == 1 and world.output.exists()
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert b"private" not in world.output.read_bytes()


@pytest.mark.parametrize("kind", ["existing", "symlink"])
def test_create_only_output_does_not_replace_existing_evidence(world, tmp_path, kind):
    target = tmp_path / "retained.jsonl"
    target.write_bytes(b"retained-evidence\n")
    if kind == "existing":
        world.output.write_bytes(b"retained-evidence\n")
    else:
        world.output.symlink_to(target)
    with pytest.raises(diagnostic.DiagnosticError, match="^output_unavailable$"):
        world.create()
    assert world.output.read_bytes() == target.read_bytes() == b"retained-evidence\n"


def test_frame_privacy_uses_only_approved_relative_paths_and_primitives(world, monkeypatch):
    sampler = world.create()
    frames = [
        _frame(), _frame("/stdlib/threading.py", "wait"),
        _frame("/source/allowed.py", "bad-name-with-private-text"),
        _frame("/source/not_allowed.py", "hidden"),
        _frame("/source/../private.py", "hidden"),
        _frame("/source-sibling/allowed.py", "hidden"),
        _frame("/stdlib/private.py", "hidden"),
        _frame("/private/argv-key-value.py", "hidden"),
    ]
    for first, second in pairwise(frames):
        first.f_back = second
    snapshot = {101: frames[0], 202: _frame("/stdlib/threading.py", "wait"),
                999999: _frame(line=-1)}
    monkeypatch.setattr(diagnostic, "_CURRENT_FRAMES", lambda: snapshot)
    record = sampler._sample(0)
    assert snapshot == {}  # No references to observed frames survive.
    assert [item["class"] for item in record["threads"]] == ["main", "sampler", "worker"]
    assert record["frames_recorded"] == 3
    assert record["threads"][0]["unlisted_or_capped_frames"] == 6
    raw = json.dumps(record).encode()
    for private in (b"/source", b"/stdlib", b"private", b"hidden", b"999999", b"not_allowed"):
        assert private not in raw
    assert sampler.finish()["terminal_status"] == "written"


def test_sample_has_hard_frame_depth_thread_and_lifetime_slot_output_bounds(world, monkeypatch):
    sampler = world.create()
    chain = None
    for _index in range(diagnostic._MAX_DEPTH + 10):
        chain = _frame(back=chain)
    snapshot = {ident: chain for ident in range(300, 340)}
    snapshot.update({101: chain, 202: chain})
    monkeypatch.setattr(diagnostic, "_CURRENT_FRAMES", lambda: dict(snapshot))
    first = sampler._sample(0)
    assert len(first["threads"]) == diagnostic._MAX_THREADS == 32
    assert first["frames_recorded"] == diagnostic._MAX_FRAMES == 128
    assert all(item["depth_capped"] for item in first["threads"])
    assert all(len(item["frames"]) <= diagnostic._MAX_DEPTH for item in first["threads"])
    assert first["threads_omitted"] == 10
    for offset in (1000, 2000, 3000):
        monkeypatch.setattr(diagnostic, "_CURRENT_FRAMES",
                            lambda offset=offset: {offset + i: chain for i in range(40)})
        record = sampler._sample(1)
        assert len(sampler.slots) <= diagnostic._MAX_SLOTS
        assert len(record["threads"]) <= diagnostic._MAX_THREADS
        assert len(json.dumps(record).encode()) <= diagnostic._MAX_RECORD_BYTES
    assert len(sampler.slots) == diagnostic._MAX_SLOTS == 64
    assert sampler.finish()["terminal_status"] == "written"


@pytest.mark.parametrize("allowed", [
    [], ["x.py"] * 2, ["/x.py"], ["a/../x.py"], ["a//x.py"], ["./x.py"],
    ["x.py\n"], ["x\\y.py"], ["\ud800.py"], ["字" * 171 + ".py"],
    ["x.txt"], [True], iter(["x.py"]),
])
def test_allowlist_is_bounded_canonical_exact_text(allowed):
    with pytest.raises(diagnostic.DiagnosticError, match="^allowlist_invalid$"):
        diagnostic.checked_allowlist(allowed)


@pytest.mark.parametrize("root", ["relative", "//a", "/a/", "/a/./b", "/a/../b", "/a\n", "/\ud800", None])
def test_root_refusal_precedes_output_creation(world, root):
    with pytest.raises(diagnostic.DiagnosticError, match="^root_invalid$"):
        diagnostic.StackSampler(root, ["allowed.py"], world.output, stdlib_root="/stdlib")
    assert not world.output.exists()


@pytest.mark.parametrize("field,value,code", [
    ("seconds", 0, "duration_invalid"), ("seconds", 180.1, "duration_invalid"),
    ("seconds", float("nan"), "duration_invalid"), ("seconds", True, "duration_invalid"),
    ("seconds", 1 << 5000, "duration_invalid"),
    ("interval", 0.1, "interval_invalid"), ("interval", True, "interval_invalid"),
])
def test_numeric_configuration_is_bounded_before_output(world, field, value, code):
    with pytest.raises(diagnostic.DiagnosticError, match="^" + code + "$"):
        diagnostic.StackSampler("/source", ["allowed.py"], world.output,
                                stdlib_root="/stdlib", **{field: value})
    assert not world.output.exists()
