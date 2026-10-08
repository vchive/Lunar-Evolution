"""Pure Feature191 terminal/observation and unknown-reconcile contracts."""

from __future__ import annotations

import json

import pytest

from lunar_evolution.python_producer_lifecycle import (
    PythonProducerLifecycleError,
    build_python_producer_runtime_observation,
    build_python_producer_terminal,
    parse_python_producer_runtime_observation,
    parse_python_producer_terminal,
    reconcile_python_producer_terminal,
    resume_python_producer_terminal,
)

D = "a" * 64


def terminal(**changes):
    value = {
        "binding_sha256": D,
        "run_id": "run-1",
        "journal_id": "journal-1",
        "launch_id": "launch-1",
        "process_registration_sha256": None,
        "owner_identity_sha256": None,
        "executable_sha256": None,
        "executable_size": None,
        "executable_device": None,
        "executable_inode": None,
        "started_unix": 10.0,
        "released_unix": None,
        "exited_unix": None,
        "deadline_unix": 100.0,
        "status": "unknown",
        "exit_code": None,
        "signal": None,
        "cleanup_status": "missing",
        "request_journal_sha256": None,
        "request_count": 0,
        "stdout_sha256": D,
        "stderr_sha256": D,
        "publication_eligible": False,
    }
    value.update(changes)
    return build_python_producer_terminal(**value)


def completed_terminal(**changes):
    value = {
        "process_registration_sha256": D,
        "owner_identity_sha256": D,
        "executable_sha256": D,
        "executable_size": 10,
        "executable_device": 1,
        "executable_inode": 2,
        "released_unix": 11.0,
        "exited_unix": 12.0,
        "status": "completed",
        "exit_code": 0,
        "cleanup_status": "cleaned",
        "request_journal_sha256": D,
        "request_count": 1,
    }
    value.update(changes)
    return terminal(**value)


def observation():
    return build_python_producer_runtime_observation(
        binding_sha256=D,
        execution_performed=True,
        version_major=3,
        version_minor=13,
        version_micro=12,
        cache_tag="cpython-313",
        abi_profile="cp313-ordinary-gil",
        argv=("fixture", "--fixed"),
        orig_argv=("fixture", "--fixed"),
        flags=("-B", "-I", "-S"),
        filesystem_encoding="utf-8",
        filesystem_errors="surrogateescape",
        stdio_encoding="utf-8",
        stdio_errors="surrogateescape",
        sys_path=(".",),
        startup_modules=("_io", "site"),
        broker_transcript_sha256=D,
        pycache_absent=True,
        computation_sha256=D,
    )


def test_unknown_terminal_roundtrip_is_not_publication_eligible():
    item = terminal()
    assert item.terminal_sha256 == item.digest()
    assert parse_python_producer_terminal(item.to_json()) == item
    assert item.publication_eligible is False


def test_completed_terminal_roundtrip_and_resume_is_read_only():
    item = completed_terminal()
    replay = resume_python_producer_terminal(
        item.to_json(), expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    )
    assert replay == item
    assert parse_python_producer_terminal(item.to_json()) == item


def test_unknown_reconcile_requires_complete_process_and_cleanup_evidence():
    old = terminal()
    current = completed_terminal()
    assert reconcile_python_producer_terminal(
        old, current, expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    ) == current
    assert reconcile_python_producer_terminal(
        old, old, expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    ) == old
    with pytest.raises(PythonProducerLifecycleError, match="reconcile_evidence_missing"):
        reconcile_python_producer_terminal(
            old, terminal(status="failed", cleanup_status="unknown"),
            expected_binding={"binding_sha256": D, "deadline_unix": 100.0},
        )


def test_reconcile_rejects_binding_or_deadline_drift_and_terminal_mutation():
    old = completed_terminal()
    with pytest.raises(PythonProducerLifecycleError, match="binding_drift"):
        reconcile_python_producer_terminal(old, old, expected_binding={"binding_sha256": "b" * 64, "deadline_unix": 100.0})
    with pytest.raises(PythonProducerLifecycleError, match="deadline_drift"):
        reconcile_python_producer_terminal(old, old, expected_binding={"binding_sha256": D, "deadline_unix": 101.0})
    with pytest.raises(PythonProducerLifecycleError, match="terminal_immutable"):
        reconcile_python_producer_terminal(
            old, completed_terminal(request_count=2), expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
        )


def test_observation_is_canonical_and_protection_claims_stay_false():
    item = observation()
    assert item.observation_sha256 == item.digest()
    assert parse_python_producer_runtime_observation(item.to_json()) == item
    payload = json.loads(item.to_json())
    payload["production_admission"] = True
    with pytest.raises(PythonProducerLifecycleError, match="unsupported_protection_claim"):
        parse_python_producer_runtime_observation(payload)


def test_parser_rejects_duplicate_and_noncanonical_json():
    raw = terminal().to_json()
    with pytest.raises(PythonProducerLifecycleError, match="duplicate_json_key"):
        parse_python_producer_terminal(raw[:-1] + b',"status":"unknown"}')
    with pytest.raises(PythonProducerLifecycleError, match="noncanonical_json"):
        parse_python_producer_terminal(json.dumps(json.loads(raw), indent=2))
    with pytest.raises(PythonProducerLifecycleError, match="reconcile_required"):
        resume_python_producer_terminal(terminal(), expected_binding={"binding_sha256": D, "deadline_unix": 100.0})
