"""Pure failure DTO plus inert filesystem sibling conflicts; no native process is run."""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import subprocess
from dataclasses import replace

import pytest
from test_producer_bootstrap import _formal_registration
from test_rsi_native_rejection import digest, rejection_evidence

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_deadline_binding import NATIVE_CONSUMPTION_PROTOCOL
from lunar_evolution.native_trusted_attempt import _terminal_receipt
from lunar_evolution.native_trusted_failure import (
    NATIVE_TRUSTED_FAILURE_PROTOCOL,
    NativeTrustedProducerFailure,
)
from lunar_evolution.producer_bootstrap import TrustedBootstrapEvidence
from lunar_evolution.producer_request_transport import HostRequestJournalIdentity
from lunar_evolution.rsi_native_failure import (
    NATIVE_RSI_FAILURE_PROVENANCE_NAME,
    NativeRSIFailureError,
    NativeRSIFailureEvidence,
    persist_native_rsi_failure_provenance,
    read_native_rsi_failure_provenance,
)
from lunar_evolution.rsi_native_provenance import NATIVE_RSI_PROVENANCE_NAME
from lunar_evolution.rsi_native_provenance_names import NATIVE_RSI_REJECTION_PROVENANCE_NAME
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.trusted_bootstrap_handoff import _handoff_payload


@pytest.fixture(autouse=True)
def forbid_processes_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("pure failure provenance tests must not start processes or connect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def hashed_record(value, field):
    return {**value, field: hashlib.sha256(canonical_json(value)).hexdigest()}


def pure_failure_evidence():
    """Construct a detached wire through real strict parsers, without a live authority claim."""
    seed = rejection_evidence()
    launch, descriptor, registration = _formal_registration()
    association = ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                   "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256")
    plan = replace(seed.plan, **{name: getattr(launch, name) for name in association}, plan_sha256=None)
    deadline = hashed_record({
        "schema_version": "1", "protocol": "lunar-native-trusted-attempt-deadline-v1",
        **{name: getattr(launch, name) for name in (
            "launch_id", "journal_id", "launch_sha256", "intent_sha256", "attestation_sha256",
        )},
        "started_monotonic": 10.0, "deadline_monotonic": 20.0, "boot_id": "inert-boot",
    }, "deadline_sha256")
    deadline_bytes = canonical_json(deadline)
    consumption = hashed_record({
        "schema_version": "2", "protocol": NATIVE_CONSUMPTION_PROTOCOL,
        "consumption_id": launch.launch_id, "nonce": launch.gate_nonce,
        **{name: getattr(launch, name) for name in association if name != "bootstrap_descriptor_sha256"},
        "executable_identity": digest("inert-target-original-identity"),
        "deadline_binding": {
            "schema_version": "1", "protocol": "lunar-native-deadline-file-binding-v1",
            "name": "native-trusted-attempt-deadline.json", "deadline_sha256": deadline["deadline_sha256"],
            "raw_sha256": hashlib.sha256(deadline_bytes).hexdigest(), "size": len(deadline_bytes),
            "device": 3, "inode": 4, "mode": 0o600, "mtime_ns": 5, "ctime_ns": 6,
        },
    }, "consumption_sha256")
    registration["consumption_sha256"] = consumption["consumption_sha256"]
    registration = hashed_record({name: value for name, value in registration.items()
                                  if name != "registration_sha256"}, "registration_sha256")
    handoff = hashed_record(_handoff_payload(
        launch=launch, descriptor=descriptor, consumption=consumption, registration=registration,
    ), "handoff_sha256")
    bootstrap_evidence = TrustedBootstrapEvidence(
        launch_sha256=launch.digest(), registration_sha256=registration["registration_sha256"],
        bootstrap_ready_observed=True, release_observed=True, target_started_observed=True,
        target_start_count=1, target_group_identity=hashlib.sha256(canonical_json({"pid": 1235, "pgid": 1234})).hexdigest(),
        target_pid=1235, target_pgid=1234, pre_gate_target_work_observed=False, status="passed",
    )
    cleanup = hashed_record({
        "schema_version": "1", "protocol": "lunar-native-trusted-cleanup-v1",
        **{name: registration[name] for name in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
            "registration_sha256", "pid", "pgid",
        )},
        "deadline_sha256": deadline["deadline_sha256"], "cleanup_status": "already_exited",
        "term_sent": False, "kill_sent": False, "alive_after": False, "publication_eligible": False,
    }, "cleanup_sha256")
    terminal = _terminal_receipt(
        registration, handoff_sha256=handoff["handoff_sha256"],
        evidence_sha256=bootstrap_evidence.evidence_sha256, gate_released=True, target_started=True,
        exit_code=7, cleanup_status=cleanup["cleanup_status"], deadline_sha256=deadline["deadline_sha256"],
        cleanup_sha256=cleanup["cleanup_sha256"],
    )
    broker_identity = HostRequestJournalIdentity(
        **{name: getattr(launch, name) for name in association
           if name not in {"attestation_sha256", "bootstrap_descriptor_sha256"}},
        request_timeout_seconds=1, max_requests=1, wall_deadline_ns=20_000_000_000,
    )
    failure = NativeTrustedProducerFailure.from_dict(hashed_record({
        "schema_version": "1", "protocol": NATIVE_TRUSTED_FAILURE_PROTOCOL, "status": "failed",
        "receipt_scope": "process_only", "publication_eligible": False,
        "launch": launch.to_dict(), "descriptor": descriptor.to_dict(), "consumption": consumption,
        "registration": registration, "handoff": handoff, "bootstrap_evidence": bootstrap_evidence.to_dict(),
        "deadline_record": deadline, "terminal_record": terminal, "cleanup_record": cleanup,
        "stream_capture": None,
        "broker": {
            "journal_relative_path": ".host-request-journal/requests", "journal_identity": broker_identity.to_dict(),
            "journal_sha256": digest("inert-broker-journal"), "journal_bytes": 1,
            "journal_file_identity": {"device": 7, "inode": 8}, "complete": True,
            "snapshot": {
                "events": [], "admitted_count": 0, "active_count": 0,
                "request_timeout_seconds": 1, "max_requests": 1,
                "coverage": "brokered_requests_only", "clock_source": "controller_monotonic",
            },
        },
    }, "failure_sha256"))
    claim = replace(seed.claim, plan_sha256=plan.plan_sha256, claim_sha256=RSILedger._native_claim_digest(
        seed.claim.episode_id, seed.claim.request_sha256, plan.plan_sha256,
    ))
    return NativeRSIFailureEvidence(
        plan=plan, failure=failure, input_binding_sha256=seed.input_binding_sha256,
        ledger_identity=seed.ledger_identity, claim=claim,
    )


def image(root):
    observation = {}
    for path in sorted(root.iterdir()):
        info = path.lstat()
        metadata = (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns)
        observation[path.name] = (metadata, os.readlink(path) if path.is_symlink() else path.read_bytes())
    return observation


def test_pure_failure_dto_and_original_writer_roundtrip(tmp_path):
    evidence = pure_failure_evidence()
    assert NativeRSIFailureEvidence.from_dict(evidence.to_dict()) == evidence
    assert evidence.failure.status == "failed" and evidence.failure.exit_code == 7
    assert evidence.failure.to_dict()["publication_eligible"] is False
    written = persist_native_rsi_failure_provenance(tmp_path, evidence)
    retained = read_native_rsi_failure_provenance(tmp_path)
    assert retained == replace(evidence, provenance_sha256=written)
    assert stat.S_IMODE((tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME).stat().st_mode) == 0o400
    before = image(tmp_path)
    assert persist_native_rsi_failure_provenance(tmp_path, evidence) == written
    assert persist_native_rsi_failure_provenance(tmp_path, retained) == written
    assert image(tmp_path) == before


@pytest.mark.parametrize("sibling", [NATIVE_RSI_PROVENANCE_NAME, NATIVE_RSI_REJECTION_PROVENANCE_NAME])
@pytest.mark.parametrize("kind", ["partial", "symlink"])
def test_original_failure_writer_refuses_each_existing_sibling_without_creating_or_mutating(tmp_path, sibling, kind):
    evidence = pure_failure_evidence()
    target = tmp_path / "untouched-target"
    target.write_bytes(b"retained sibling target")
    path = tmp_path / sibling
    if kind == "partial":
        path.write_bytes(b'{"partial":')
    else:
        path.symlink_to(target.name)
    before = image(tmp_path)
    with pytest.raises(NativeRSIFailureError, match="rsi_native_failure_conflicting_provenance"):
        persist_native_rsi_failure_provenance(tmp_path, evidence)
    assert not os.path.lexists(tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME)
    assert image(tmp_path) == before
