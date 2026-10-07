"""Native known-failure evidence uses inert C targets and retained local journals only."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_native_trusted_attempt import _attempt

import lunar_evolution.native_trusted_failure as failure_module
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_trusted_attempt import (
    recover_native_trusted_attempt,
    run_native_trusted_attempt,
)
from lunar_evolution.native_trusted_failure import (
    NativeTrustedFailureError,
    NativeTrustedProducerFailure,
    build_native_trusted_failure,
    recover_native_trusted_failure,
)
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_process import ProducerProcessError
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    read_host_request_journal,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="native local platform")


def make_failure(tmp_path: Path, *, cancelled: bool = False):
    workspace, producer, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=8, target_exit=7, target_sleep=12 if cancelled else 0,
        mark_started_before_sleep=cancelled,
    )
    marker_seen = [None]

    def cancellation():
        if (batch / "work" / "marker").exists():
            marker_seen[0] = marker_seen[0] or time.monotonic()
        return marker_seen[0] is not None and time.monotonic() - marker_seen[0] >= 0.2

    arguments = {"intent": intent, "attestation": attestation, "artifact": artifact}
    attempt = run_native_trusted_attempt(
        workspace, producer_root=producer, **arguments,
        broker_config=ProducerBrokerConfig("http://127.0.0.1:1", {}),
        cancelled=cancellation if cancelled else None,
    )
    proof = build_native_trusted_failure(workspace, **arguments, attempt=attempt)
    return SimpleNamespace(
        workspace=workspace, producer=producer, arguments=arguments, attempt=attempt, proof=proof, batch=batch,
    )


@pytest.fixture(scope="module")
def failed(tmp_path_factory):
    return make_failure(tmp_path_factory.mktemp("native-known-failed"))


def image(root: Path):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_dev, path.stat().st_ino, path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def rehash(payload):
    payload["failure_sha256"] = hashlib.sha256(canonical_json({
        key: value for key, value in payload.items() if key != "failure_sha256"
    }, maximum=failure_module.MAX_NATIVE_TRUSTED_FAILURE_BYTES)).hexdigest()
    return payload


def rehash_record(record, digest_field):
    record[digest_field] = hashlib.sha256(canonical_json({
        key: value for key, value in record.items() if key != digest_field
    })).hexdigest()


def refresh_wire_links(wire):
    for record, field, terminal_field in (
        ("stream_capture", "stream_capture_sha256", "stream_capture_sha256"),
        ("handoff", "handoff_sha256", "handoff_sha256"),
        ("bootstrap_evidence", "evidence_sha256", "bootstrap_evidence_sha256"),
    ):
        rehash_record(wire[record], field)
        wire["terminal_record"][terminal_field] = wire[record][field]
    rehash_record(wire["terminal_record"], "terminal_sha256")
    return rehash(wire)


def test_actual_nonzero_preserves_all_records_and_original_broker_pin(failed, monkeypatch):
    proof = failed.proof
    assert proof.status == "failed" and proof.exit_code == 7
    raw = proof.to_dict()
    assert raw["terminal_record"]["protocol"] == "lunar-native-trusted-process-terminal-v1"
    assert raw["consumption"]["protocol"] == "lunar-native-trusted-attestation-consumption-v2"
    assert raw["broker"]["journal_sha256"] == failed.attempt.broker_observation.journal_sha256
    assert raw["broker"]["journal_file_identity"] == dict(zip(
        ("device", "inode"), failed.attempt.broker_observation.journal_file_identity, strict=True,
    ))
    assert raw["broker"]["snapshot"]["admitted_count"] == 0
    assert raw["broker"]["complete"] is True
    assert raw["publication_eligible"] is False
    before = image(failed.workspace)

    def forbidden(*args, **kwargs):
        pytest.fail("failure recovery must not launch, write, signal, or call a provider")

    import lunar_evolution.native_trusted_attempt as attempt_module
    monkeypatch.setattr(attempt_module, "cleanup_registered_process", forbidden)
    monkeypatch.setattr(attempt_module.subprocess, "Popen", forbidden)
    assert recover_native_trusted_failure(failed.workspace, **failed.arguments, expected=proof) == proof
    assert image(failed.workspace) == before


def test_actual_active_cancellation_accepts_its_exact_unknown_handshake(tmp_path):
    fixture = make_failure(tmp_path, cancelled=True)
    proof = fixture.proof
    assert proof.status == "cancelled" and proof.exit_code is None
    assert proof.terminal_record["gate_released"] is True
    assert proof.terminal_record["target_started"] is True
    assert proof.to_dict()["bootstrap_evidence"]["status"] == "unknown"
    assert recover_native_trusted_failure(fixture.workspace, **fixture.arguments, expected=proof) == proof


def test_wire_roundtrip_and_properties_cannot_mutate_frozen_proof(failed):
    proof = failed.proof
    wire = proof.to_dict()
    assert NativeTrustedProducerFailure.from_dict(wire) == proof
    assert NativeTrustedProducerFailure.from_dict(wire).digest() == proof.digest()
    wire["terminal_record"]["exit_code"] = 0
    proof.terminal_record["exit_code"] = 0
    assert proof.exit_code == 7
    assert proof.terminal_sha256 == failed.attempt.terminal_sha256


@pytest.mark.parametrize("mutation", [
    "stream_extra", "stream_schema", "stream_protocol", "stream_task", "stream_registration",
    "stream_deadline", "stream_limit_bool", "stream_limit_negative", "stream_bytes_bool",
    "stream_bytes_overflow", "stream_digest", "stream_truncated", "stream_status", "stream_item_extra",
    "handoff_bootstrap_size", "handoff_target_size", "handoff_target_digest", "evidence_target_group",
    "evidence_unknown",
])
def test_rehashed_nested_records_must_keep_exact_types_schema_and_bindings(failed, mutation):
    wire = failed.proof.to_dict()
    streams = wire["stream_capture"]
    item = streams["stdout_evidence"]
    if mutation == "stream_extra":
        streams["extra"] = True
    elif mutation in {"stream_schema", "stream_protocol", "stream_task", "stream_registration", "stream_deadline"}:
        field, value = {
            "stream_schema": ("schema_version", "2"), "stream_protocol": ("protocol", "other"),
            "stream_task": ("task_id", "other-task"), "stream_registration": ("registration_sha256", "b" * 64),
            "stream_deadline": ("deadline_sha256", "b" * 64),
        }[mutation]
        streams[field] = value
    elif mutation in {"stream_limit_bool", "stream_limit_negative"}:
        streams["output_max_bytes"] = True if mutation == "stream_limit_bool" else -1
    elif mutation in {"stream_bytes_bool", "stream_bytes_overflow"}:
        item["bytes_observed"] = True if mutation == "stream_bytes_bool" else streams["output_max_bytes"] + 2
    elif mutation == "stream_digest":
        item["sha256"] = "invalid"
    elif mutation == "stream_truncated":
        item["truncated"] = 1
    elif mutation == "stream_status":
        item["capture_status"] = "unknown"
    elif mutation == "stream_item_extra":
        item["extra"] = True
    elif mutation.startswith("handoff_"):
        field = {
            "handoff_bootstrap_size": "bootstrap_snapshot_size", "handoff_target_size": "target_snapshot_size",
            "handoff_target_digest": "target_snapshot_sha256",
        }[mutation]
        wire["handoff"][field] = "b" * 64 if field.endswith("sha256") else wire["handoff"][field] + 1
    elif mutation == "evidence_target_group":
        evidence = wire["bootstrap_evidence"]
        evidence["target_pgid"] += 1
        evidence["target_group_identity"] = hashlib.sha256(canonical_json({
            "pid": evidence["target_pid"], "pgid": evidence["target_pgid"],
        })).hexdigest()
    else:
        wire["bootstrap_evidence"]["status"] = "unknown"
    with pytest.raises(NativeTrustedFailureError):
        NativeTrustedProducerFailure.from_dict(refresh_wire_links(wire))


@pytest.mark.parametrize("mutation", [
    "extra", "schema", "protocol", "status", "scope", "publication", "digest", "exit_zero", "exit_bool",
    "consumption_legacy", "consumption_no_anchor", "cleanup_alive", "unrelated_terminal", "streams_unbound",
    "broker_missing_inode", "broker_uncertain", "broker_snapshot_count", "broker_relative_path",
])
def test_rehashed_wire_cannot_relax_failure_contract(failed, mutation):
    wire = failed.proof.to_dict()
    if mutation == "extra":
        wire["invented"] = True
    elif mutation in {"schema", "protocol", "status", "scope", "publication"}:
        field, value = {
            "schema": ("schema_version", "2"), "protocol": ("protocol", "other"),
            "status": ("status", "completed"), "scope": ("receipt_scope", "successful_execution"),
            "publication": ("publication_eligible", True),
        }[mutation]
        wire[field] = value
    elif mutation == "digest":
        wire["failure_sha256"] = "0" * 64
    elif mutation in {"exit_zero", "exit_bool"}:
        wire["terminal_record"]["exit_code"] = 0 if mutation == "exit_zero" else True
    elif mutation in {"consumption_legacy", "consumption_no_anchor"}:
        wire["consumption"].pop("deadline_binding")
        if mutation == "consumption_legacy":
            wire["consumption"]["schema_version"] = "1"
            wire["consumption"]["protocol"] = "lunar-producer-process-v1"
    elif mutation == "cleanup_alive":
        wire["cleanup_record"]["alive_after"] = True
    elif mutation == "unrelated_terminal":
        wire["terminal_record"]["task_id"] = "unrelated-task"
    elif mutation == "streams_unbound":
        wire["stream_capture"] = None
    elif mutation == "broker_missing_inode":
        wire["broker"]["journal_file_identity"] = None
    elif mutation == "broker_uncertain":
        wire["broker"]["snapshot"]["active_count"] = 1
    elif mutation == "broker_snapshot_count":
        wire["broker"]["snapshot"]["admitted_count"] = True
    else:
        wire["broker"]["journal_relative_path"] = "../alternate"
    if mutation != "digest":
        rehash(wire)
    with pytest.raises(NativeTrustedFailureError):
        NativeTrustedProducerFailure.from_dict(wire)


def test_live_broker_shutdown_flag_is_rechecked_under_original_pins(failed):
    observation = replace(failed.attempt.broker_observation, complete=False, reason="cancelled")
    attempt = replace(failed.attempt, broker_observation=observation)
    rebuilt = build_native_trusted_failure(failed.workspace, **failed.arguments, attempt=attempt)
    assert rebuilt == failed.proof


@pytest.mark.parametrize("mutation", ["missing", "sha", "bytes", "inode", "snapshot", "path"])
def test_builder_never_repins_missing_or_drifted_live_broker(failed, mutation):
    observation = failed.attempt.broker_observation
    if mutation == "missing":
        observation = None
    elif mutation == "sha":
        observation = replace(observation, journal_sha256="0" * 64)
    elif mutation == "bytes":
        observation = replace(observation, journal_bytes=observation.journal_bytes + 1)
    elif mutation == "inode":
        observation = replace(observation, journal_file_identity=(0, 0))
    elif mutation == "snapshot":
        observation = replace(observation, snapshot=replace(observation.snapshot, active_count=1))
    else:
        observation = replace(observation, journal_path=observation.journal_path.with_name("alternate"))
    before = image(failed.workspace)
    with pytest.raises(NativeTrustedFailureError):
        build_native_trusted_failure(
            failed.workspace, **failed.arguments, attempt=replace(failed.attempt, broker_observation=observation),
        )
    assert image(failed.workspace) == before


@pytest.mark.parametrize("file", [
    "native-trusted-process-terminal.json", "trusted-bootstrap-handoff.json",
    "native-trusted-attempt-deadline.json", "native-trusted-cleanup.json", "native-trusted-stream-capture.json",
])
def test_recovery_refuses_missing_original_record_without_repair(tmp_path, file):
    fixture = make_failure(tmp_path)
    (fixture.batch / file).unlink()
    before = image(fixture.workspace)
    with pytest.raises(NativeTrustedFailureError):
        recover_native_trusted_failure(fixture.workspace, **fixture.arguments, expected=fixture.proof)
    assert image(fixture.workspace) == before


def test_recovery_rejects_same_content_broker_inode_replacement(tmp_path):
    fixture = make_failure(tmp_path)
    journal = fixture.attempt.broker_observation.journal_path
    replacement = journal.with_name("replacement")
    replacement.write_bytes(journal.read_bytes())
    os.replace(replacement, journal)
    before = image(fixture.workspace)
    with pytest.raises(NativeTrustedFailureError):
        recover_native_trusted_failure(fixture.workspace, **fixture.arguments, expected=fixture.proof)
    assert image(fixture.workspace) == before


def test_cleaned_unknown_recovery_v2_never_settles_as_known_failure(tmp_path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as attempt_module

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path, target_exit=7)
    atomic_json = attempt_module._atomic_json

    def reject_terminal(path, value, *, exclusive=False):
        if path.name == "native-trusted-process-terminal.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return atomic_json(path, value, exclusive=exclusive)

    monkeypatch.setattr(attempt_module, "_atomic_json", reject_terminal)
    arguments = {"intent": intent, "attestation": attestation, "artifact": artifact}
    attempt = run_native_trusted_attempt(
        workspace, producer_root=producer, **arguments, broker_config=ProducerBrokerConfig("http://127.0.0.1:1", {}),
    )
    recovered = recover_native_trusted_attempt(workspace, **arguments, cleanup=True)
    assert recovered["schema_version"] == "2" and recovered["execution_outcome"] == "unknown"
    assert recovered["cleanup_status"] in {"cleaned", "already_exited"} and recovered["alive_after"] is False
    before = image(workspace)
    with pytest.raises(NativeTrustedFailureError, match="terminal_unknown"):
        build_native_trusted_failure(workspace, **arguments, attempt=attempt)
    assert image(workspace) == before
    assert not (batch / "native-trusted-process-terminal.json").exists()


def test_mid_broker_read_native_terminal_change_is_detected(tmp_path, monkeypatch):
    fixture = make_failure(tmp_path)
    recover = failure_module.recover_producer_broker_observation
    changed = [False]

    def drift(*args, **kwargs):
        result = recover(*args, **kwargs)
        if not changed[0]:
            changed[0] = True
            terminal = fixture.batch / "native-trusted-process-terminal.json"
            raw = json.loads(terminal.read_bytes())
            raw["exit_code"] = 9
            raw["terminal_sha256"] = hashlib.sha256(canonical_json({
                key: item for key, item in raw.items() if key != "terminal_sha256"
            })).hexdigest()
            terminal.write_bytes(canonical_json(raw))
        return result

    monkeypatch.setattr(failure_module, "recover_producer_broker_observation", drift)
    with pytest.raises(NativeTrustedFailureError, match="records_changed"):
        recover_native_trusted_failure(fixture.workspace, **fixture.arguments, expected=fixture.proof)
    assert changed == [True]


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "active", "timed_out"])
def test_closed_broker_projection_requires_actual_terminal_requests(tmp_path, status):
    identity = HostRequestJournalIdentity(
        "launch", "journal", "run", "parent", "task", "a" * 64, 1, 1, time.monotonic_ns() + 10**10,
    )
    batch = tmp_path / "batch"
    directory = batch / ".host-request-journal"
    directory.mkdir(parents=True, mode=0o700)
    journal_path = directory / "requests"
    ticks = [10**9]
    with HostRequestJournal.create(journal_path, identity) as journal:
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, journal=journal, monotonic_ns=lambda: ticks[0])
        admission = ledger.admit("req-1")
        if status != "active":
            if status == "timed_out":
                ticks[0] += 2 * 10**9
                ledger.expire()
            else:
                ledger.finish(admission, status=status)
    read = read_host_request_journal(journal_path, expected_identity=identity)
    pin = {
        "journal_relative_path": ".host-request-journal/requests", "journal_identity": identity.to_dict(),
        "journal_sha256": read.journal_sha256, "journal_bytes": read.journal_bytes,
        "journal_file_identity": dict(zip(("device", "inode"), read.journal_file_identity, strict=True)),
    }
    intent = SimpleNamespace(request_timeout_seconds=1, max_requests=1)
    if status in {"active", "timed_out"}:
        with pytest.raises(NativeTrustedFailureError, match="broker_unsettled"):
            failure_module._closed_broker(batch, pin, intent)
    else:
        result = failure_module._closed_broker(batch, pin, intent)
        assert result["complete"] and result["snapshot"]["events"][0]["status"] == status
