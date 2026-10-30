"""Completion comparison/pipe faults, without a trusted runtime or model claim."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from dataclasses import replace

import pytest

from lunar_evolution.static_python_producer_completion import (
    COMPLETION_PROFILE,
    COMPLETION_PROTOCOL,
    MAX_COMPLETION_BYTES,
    FixedProducerCompletionBinding,
    FixedProducerCompletionError,
    NativeFixedProducerCompletionCapture,
    compare_fixed_producer_completion,
)


def _raw(records):
    return b"".join(json.dumps(item, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True).encode("ascii") + b"\n" for item in records)


def _material(raw):
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _vector(solver="openevolve"):
    binding = FixedProducerCompletionBinding(solver, 123, "a" * 64, 123456789)
    names = (("candidate.py", "result.json") if solver == "openevolve"
             else ("gen_0/main.py", "programs.sqlite"))
    arguments = {"binding": binding, "request_bytes": b"request", "memory_bytes": b"memory",
                 "request_body_bytes": b"body", "reply_bytes": b"reply",
                 "artifacts": tuple((name, name.encode()) for name in names)}
    common = {"protocol": COMPLETION_PROTOCOL, "profile": COMPLETION_PROFILE, "solver": solver,
              "manifest_sha256": binding.manifest_sha256, "target_pid": binding.target_pid,
              "deadline_monotonic_ns": binding.deadline_monotonic_ns}
    records = [{**common, "seq": 0, "phase": "begun"},
               {**common, "seq": 1, "phase": "committed",
                "request": _material(arguments["request_bytes"]),
                "memory": _material(arguments["memory_bytes"]),
                "broker": {"request_id": "req-1", "request_count": 1, "status": 200,
                           "request_body": _material(arguments["request_body_bytes"]),
                           "reply": _material(arguments["reply_bytes"])},
                "artifacts": [{"path": name, **_material(raw)} for name, raw in arguments["artifacts"]]}]
    return records, arguments


@pytest.mark.parametrize("solver", ["openevolve", "shinka"])
def test_completion_joins_material_in_commit_order_without_original_authority(solver):
    records, arguments = _vector(solver)
    raw = _raw(records)
    result = compare_fixed_producer_completion(raw, **arguments)
    assert result.canonical_bytes is raw
    assert result.completion_sha256 == hashlib.sha256(raw).hexdigest()
    assert tuple(name for name, _digest in result.artifact_sha256s) == tuple(name for name, _content in arguments["artifacts"])
    assert not result.original_acquisition_verified
    assert not result.production_admission and not result.online_publication


@pytest.mark.parametrize("field", ["request_bytes", "memory_bytes", "request_body_bytes", "reply_bytes", "artifacts"])
def test_completion_refuses_material_disagreement(field):
    records, arguments = _vector()
    if field == "artifacts":
        arguments[field] = (("candidate.py", b"changed"), arguments[field][1])
    else:
        arguments[field] += b"changed"
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_completion(_raw(records), **arguments)


@pytest.mark.parametrize("field,value", [("target_pid", 124), ("solver", "shinka"),
                                         ("manifest_sha256", "b" * 64), ("deadline_monotonic_ns", 123456790)])
def test_completion_refuses_same_bytes_bound_to_different_launch(field, value):
    records, arguments = _vector()
    arguments["binding"] = replace(arguments["binding"], **{field: value})
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_completion(_raw(records), **arguments)


@pytest.mark.parametrize("fault", ["only-begun", "only-committed", "reversed", "duplicate", "no-eof-line",
                                  "pretty", "duplicate-key", "foreign-key", "bool-sequence", "bool-size",
                                  "broker-retry", "broker-failure", "reordered-artifacts", "foreign-artifact",
                                  "oversize", "renewed-deadline"])
def test_completion_refuses_partial_noncanonical_replayed_or_inconsistent_phases(fault):
    records, arguments = _vector()
    records = copy.deepcopy(records)
    if fault == "only-begun":
        records = records[:1]
    elif fault == "only-committed":
        records = records[1:]
    elif fault == "reversed":
        records.reverse()
    elif fault == "duplicate":
        records.append(records[1])
    elif fault == "foreign-key":
        records[1]["production_admission"] = True
    elif fault == "bool-sequence":
        records[1]["seq"] = True
    elif fault == "bool-size":
        records[1]["request"]["size"] = True
    elif fault == "broker-retry":
        records[1]["broker"]["request_count"] = 2
    elif fault == "broker-failure":
        records[1]["broker"]["status"] = 500
    elif fault == "reordered-artifacts":
        records[1]["artifacts"].reverse()
    elif fault == "foreign-artifact":
        records[1]["artifacts"][0]["path"] = "../candidate.py"
    elif fault == "renewed-deadline":
        records[1]["deadline_monotonic_ns"] += 1
    raw = _raw(records)
    if fault == "no-eof-line":
        raw = raw[:-1]
    elif fault == "pretty":
        raw = b" " + raw
    elif fault == "duplicate-key":
        raw = raw.replace(b'"seq":0', b'"seq":0,"seq":0')
    elif fault == "oversize":
        raw += b" " * MAX_COMPLETION_BYTES
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_completion(raw, **arguments)


def _writer(fd, raw, completed):
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
    except BrokenPipeError:
        pass
    finally:
        os.close(fd)
        completed.set()


def test_original_pipe_drains_concurrently_before_owner_waits_for_completion():
    read_fd, write_fd = os.pipe()
    capture = NativeFixedProducerCompletionCapture(read_fd, deadline=time.monotonic() + 3).start()
    # Larger than a minimum Linux pipe: waiting for terminal before reading can
    # deadlock the writer; the owned background reader must keep it progressing.
    raw = b"x" * MAX_COMPLETION_BYTES
    completed = threading.Event()
    writer = threading.Thread(target=_writer, args=(write_fd, raw, completed))
    writer.start()
    try:
        assert completed.wait(2)
        assert capture.finish() == raw
        assert capture.partial_bytes == raw
        assert not capture._thread.is_alive()
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        capture.cancel()
        writer.join(1)


@pytest.mark.parametrize("fault", ["empty", "oversize", "cancelled", "partial-no-eof"])
def test_pipe_unknown_states_never_become_success_or_reset_deadline(fault):
    read_fd, write_fd = os.pipe()
    deadline = time.monotonic() + (0.2 if fault == "partial-no-eof" else 3)
    capture = NativeFixedProducerCompletionCapture(read_fd, deadline=deadline).start()
    writer = None
    try:
        if fault == "empty":
            os.close(write_fd)
            write_fd = -1
        elif fault == "oversize":
            writer = threading.Thread(target=_writer,
                                      args=(write_fd, b"x" * (MAX_COMPLETION_BYTES + 1), threading.Event()))
            writer.start()
            write_fd = -1
        elif fault == "cancelled":
            capture.cancel()
        else:
            os.write(write_fd, b"partial")
        with pytest.raises(FixedProducerCompletionError):
            capture.finish()
        assert capture._deadline == deadline
        assert len(capture.partial_bytes) <= MAX_COMPLETION_BYTES + 1
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        capture._stop.set()
        capture._thread.join(1)
        assert not capture._thread.is_alive()
        if writer is not None:
            writer.join(1)
            assert not writer.is_alive()


@pytest.mark.parametrize("deadline", [True, float("inf"), float("nan"), -1.0])
def test_reader_rejects_invalid_or_expired_original_deadline_before_ownership(deadline):
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(FixedProducerCompletionError, match="context_invalid"):
            NativeFixedProducerCompletionCapture(read_fd, deadline=deadline)
        os.fstat(read_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_reader_rejects_writer_end_before_ownership():
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(FixedProducerCompletionError, match="context_invalid"):
            NativeFixedProducerCompletionCapture(write_fd, deadline=time.monotonic() + 3)
        os.fstat(write_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_changed_descriptor_is_not_closed_or_acquired_by_start():
    read_fd, write_fd = os.pipe()
    other_reader, other_writer = os.pipe()
    capture = NativeFixedProducerCompletionCapture(read_fd, deadline=time.monotonic() + 3)
    try:
        os.dup2(other_reader, read_fd)
        with pytest.raises(FixedProducerCompletionError, match="reader_changed"):
            capture.start()
        assert os.fstat(read_fd).st_ino == os.fstat(other_reader).st_ino
    finally:
        for fd in (read_fd, write_fd, other_reader, other_writer):
            os.close(fd)


def test_thread_start_failure_is_fixed_on_subsequent_finish_and_cancel(monkeypatch):
    read_fd, write_fd = os.pipe()
    capture = NativeFixedProducerCompletionCapture(read_fd, deadline=time.monotonic() + 3)

    def failed_start(_thread):
        raise RuntimeError("foreign thread failure")

    monkeypatch.setattr(threading.Thread, "start", failed_start)
    try:
        for operation in (capture.start, capture.finish, capture.cancel):
            with pytest.raises(FixedProducerCompletionError, match="start_unknown"):
                operation()
        os.fstat(read_fd)
    finally:
        os.close(read_fd)
        os.close(write_fd)
