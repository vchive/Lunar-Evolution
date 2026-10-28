"""Pure v2 envelope facts, without a trusted runtime or model claim."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from lunar_evolution.static_python_producer_completion import (
    MAX_COMPLETION_BYTES,
    FixedProducerCompletionBinding,
    FixedProducerCompletionError,
    compare_fixed_producer_completion,
)
from lunar_evolution.static_python_producer_envelope_completion import (
    compare_fixed_producer_envelope_completion,
)
from lunar_evolution.static_python_producer_envelope_source import (
    FIXED_PRODUCER_ENVELOPE_PROFILE,
    FIXED_PRODUCER_ENVELOPE_PROTOCOL,
    FixedProducerEnvelopeSourceError,
    fixed_producer_envelope_launch_argv,
    validate_fixed_producer_envelope_argv,
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
                 "request_body_bytes": b"body", "reply_bytes": b"reply", "envelope_bytes": b"original-envelope",
                 "artifacts": tuple((name, name.encode()) for name in names)}
    common = {"protocol": FIXED_PRODUCER_ENVELOPE_PROTOCOL, "profile": FIXED_PRODUCER_ENVELOPE_PROFILE, "solver": solver,
              "manifest_sha256": binding.manifest_sha256, "target_pid": binding.target_pid,
              "deadline_monotonic_ns": binding.deadline_monotonic_ns}
    records = [{**common, "seq": 0, "phase": "begun"},
               {**common, "seq": 1, "phase": "committed",
                "envelope": {"path": "producer-result.json", **_material(arguments["envelope_bytes"])},
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
    result = compare_fixed_producer_envelope_completion(raw, **arguments)
    assert result.canonical_bytes is raw
    assert result.completion_sha256 == hashlib.sha256(raw).hexdigest()
    assert tuple(name for name, _digest in result.artifact_sha256s) == tuple(name for name, _content in arguments["artifacts"])
    assert not result.original_acquisition_verified
    assert not result.production_admission and not result.online_publication


@pytest.mark.parametrize("field", ["request_bytes", "memory_bytes", "request_body_bytes", "reply_bytes", "artifacts", "envelope_bytes"])
def test_completion_refuses_material_disagreement(field):
    records, arguments = _vector()
    if field == "artifacts":
        arguments[field] = (("candidate.py", b"changed"), arguments[field][1])
    else:
        arguments[field] += b"changed"
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_envelope_completion(_raw(records), **arguments)


@pytest.mark.parametrize("field,value", [("target_pid", 124), ("solver", "shinka"),
                                         ("manifest_sha256", "b" * 64), ("deadline_monotonic_ns", 123456790)])
def test_completion_refuses_same_bytes_bound_to_different_launch(field, value):
    records, arguments = _vector()
    arguments["binding"] = replace(arguments["binding"], **{field: value})
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_envelope_completion(_raw(records), **arguments)


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
        compare_fixed_producer_envelope_completion(raw, **arguments)



@pytest.mark.parametrize("fault", ["path", "bool-size", "digest", "foreign-field", "missing", "empty-material", "large-material"])
def test_v2_envelope_requires_exact_named_original_bytes(fault):
    records, arguments = _vector()
    if fault == "path":
        records[1]["envelope"]["path"] = "../producer-result.json"
    elif fault == "bool-size":
        records[1]["envelope"]["size"] = True
    elif fault == "digest":
        records[1]["envelope"]["sha256"] = "f" * 64
    elif fault == "foreign-field":
        records[1]["envelope"]["production_admission"] = True
    elif fault == "missing":
        del records[1]["envelope"]
    else:
        arguments["envelope_bytes"] = b"" if fault == "empty-material" else b"x" * (128 * 1024 + 1)
        records[1]["envelope"] = {"path": "producer-result.json", **_material(arguments["envelope_bytes"])}
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_envelope_completion(_raw(records), **arguments)


def test_v1_and_v2_wire_never_accept_each_others_shapes():
    records, arguments = _vector()
    v1_arguments = {key: value for key, value in arguments.items() if key != "envelope_bytes"}
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_completion(_raw(records), **v1_arguments)
    for record in records:
        record["profile"] = "fixed-producer-lifecycle-v1"
        record["protocol"] = "lunar-fixed-producer-completion-v1"
    del records[1]["envelope"]
    compare_fixed_producer_completion(_raw(records), **v1_arguments)
    with pytest.raises(FixedProducerCompletionError):
        compare_fixed_producer_envelope_completion(_raw(records), **arguments)


def test_exact_argv_delivers_run_and_fingerprint_before_unchanged_input_tail():
    arguments = {"run_id": "original-run", "producer_fingerprint": "f" * 64, "manifest_sha256": "a" * 64}
    argv = fixed_producer_envelope_launch_argv("producer", **arguments)
    assert argv == ("producer", "--lunar-fixed-producer-envelope-v1", "original-run", "f" * 64,
                    "--lunar-rsi-input-v1", "a" * 64)
    assert validate_fixed_producer_envelope_argv(argv, **arguments) is None
    for index in (1, 2, 3, 4, 5):
        changed = list(argv)
        changed[index] += "x"
        with pytest.raises(FixedProducerEnvelopeSourceError):
            validate_fixed_producer_envelope_argv(tuple(changed), **arguments)
    with pytest.raises(FixedProducerEnvelopeSourceError):
        validate_fixed_producer_envelope_argv(list(argv), **arguments)


@pytest.mark.parametrize("field,value", [
    ("run_id", ""), ("run_id", "../escape"), ("run_id", "secret=value"),
    ("run_id", "日本語"), ("run_id", "x" * 129), ("run_id", True),
    ("producer_fingerprint", "F" * 64), ("producer_fingerprint", "f" * 63),
    ("manifest_sha256", True), ("manifest_sha256", "a" * 63),
])
def test_argv_builder_refuses_unbounded_or_nonidentifier_fields(field, value):
    arguments = {"run_id": "original-run", "producer_fingerprint": "f" * 64, "manifest_sha256": "a" * 64}
    arguments[field] = value
    with pytest.raises(FixedProducerEnvelopeSourceError):
        fixed_producer_envelope_launch_argv("producer", **arguments)
