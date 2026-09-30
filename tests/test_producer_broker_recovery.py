from __future__ import annotations

import hashlib
import time

import pytest

from lunar_evolution.producer_broker_ipc import (
    ProducerBrokerIpcError,
    recover_producer_broker_observation,
)
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
)


def _identity() -> HostRequestJournalIdentity:
    return HostRequestJournalIdentity(
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        intent_sha256="a" * 64,
        request_timeout_seconds=2,
        max_requests=2,
    )


def test_recovery_replays_complete_journal_and_binds_digest(tmp_path):
    path = tmp_path / "requests"
    identity = _identity()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=2,
            max_requests=2,
            journal=journal,
        )
        admission = ledger.admit("request-001")
        ledger.finish(admission, status="completed")
    raw = path.read_bytes()
    result = recover_producer_broker_observation(
        path,
        identity=identity,
        deadline_ns=time.monotonic_ns() + 5_000_000_000,
        expected_journal_sha256=hashlib.sha256(raw).hexdigest(),
        expected_journal_bytes=len(raw),
    )
    assert result.complete is True
    assert result.reason == "recovered"
    assert result.snapshot.admitted_count == 1


def test_recovery_keeps_unclosed_request_uncertain(tmp_path):
    path = tmp_path / "requests"
    identity = _identity()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=2,
            max_requests=2,
            journal=journal,
        )
        ledger.admit("request-001")
    result = recover_producer_broker_observation(
        path,
        identity=identity,
        deadline_ns=time.monotonic_ns() + 5_000_000_000,
    )
    assert result.complete is False
    assert result.reason == "recovery_required"
    assert result.snapshot.active_count == 1


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"deadline_ns": 0}, "producer_broker_recovery_input_invalid"),
        ({"deadline_ns": time.monotonic_ns() + 5_000_000_000, "expected_journal_sha256": "z" * 64},
         "producer_broker_recovery_digest_invalid"),
    ],
)
def test_recovery_rejects_invalid_boundary_inputs(tmp_path, kwargs, code):
    identity = _identity()
    with pytest.raises(ProducerBrokerIpcError) as exc:
        recover_producer_broker_observation(tmp_path / "missing", identity=identity, **kwargs)
    assert exc.value.code == code


def test_recovery_rejects_digest_drift(tmp_path):
    path = tmp_path / "requests"
    identity = _identity()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=2, journal=journal)
        admission = ledger.admit("request-001")
        ledger.finish(admission, status="completed")
    with pytest.raises(ProducerBrokerIpcError) as exc:
        recover_producer_broker_observation(
            path,
            identity=identity,
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
            expected_journal_sha256="0" * 64,
        )
    assert exc.value.code == "producer_broker_recovery_journal_mismatch"
