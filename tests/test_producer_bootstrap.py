from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution.producer_bootstrap import (
    BootstrapHandshakeFrame,
    ProducerBootstrapError,
    TrustedBootstrapDescriptor,
    TrustedBootstrapEvidence,
    TrustedBootstrapLaunch,
    TrustedBootstrapRegistration,
    TrustedBootstrapSession,
    build_trusted_bootstrap_launch,
    build_trusted_bootstrap_registration,
    observe_trusted_bootstrap_attempt,
    parse_bootstrap_handshake_frame,
    parse_trusted_bootstrap_evidence,
    parse_trusted_bootstrap_registration,
    verify_trusted_bootstrap_attempt,
    verify_trusted_bootstrap_process_registration,
    verify_trusted_bootstrap_registration,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.producer_process import PRODUCER_PROCESS_PROTOCOL

DIGEST = "a" * 64


def _descriptor() -> TrustedBootstrapDescriptor:
    return TrustedBootstrapDescriptor(
        implementation_version="bootstrap-1",
        bootstrap_sha256=DIGEST,
        size=128,
        device=1,
        inode=2,
        mtime_ns=3,
        ctime_ns=4,
        allowlist_id="local-bootstrap",
        platform_execution_mode="fixture-only",
    )


def _launch() -> TrustedBootstrapLaunch:
    return TrustedBootstrapLaunch(
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        intent_sha256=DIGEST,
        attestation_sha256=DIGEST,
        bootstrap_descriptor_sha256=_descriptor().descriptor_sha256 or _descriptor().digest(),
        target_executable_identity="b" * 64,
        gate_protocol="fd-read-one-byte-v1",
        gate_nonce="nonce-001",
    )


def _producer_admission(tmp_path: Path):
    root = tmp_path / "producer-root"
    root.mkdir()
    executable = root / "producer.py"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    executable.chmod(0o755)
    intent = build_producer_launch_intent(
        producer_root=root, launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", contract_sha256=DIGEST,
        evaluator_kind="local", evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST,
        generator_fingerprint=DIGEST, dependency_sha256=DIGEST, environment_sha256=DIGEST,
        producer_id="fixture", producer_fingerprint=DIGEST, executable_relative="producer.py",
        argv=("producer.py",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024, wall_timeout_seconds=1,
    )
    return intent, build_producer_launch_attestation(intent, "nonce-001")


def _production_descriptor() -> TrustedBootstrapDescriptor:
    return TrustedBootstrapDescriptor(
        implementation_version="bootstrap-1", bootstrap_sha256=DIGEST, size=128,
        device=1, inode=2, mtime_ns=3, ctime_ns=4, allowlist_id="local-bootstrap",
        platform_execution_mode="darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound",
    )


def _formal_registration() -> tuple[TrustedBootstrapLaunch, TrustedBootstrapDescriptor, dict[str, object]]:
    descriptor = _production_descriptor()
    launch_fields = _launch().to_dict(include_digest=False)
    launch_fields["bootstrap_descriptor_sha256"] = descriptor.descriptor_sha256
    launch = TrustedBootstrapLaunch(**launch_fields)
    owner = (
        {"kind": "darwin-libproc-starttime-v1", "pid": 1234, "start_sec": 42, "start_usec": 3}
        if sys.platform == "darwin" else
        {"kind": "linux-proc-starttime-v1", "pid": 1234, "boot_id": "boot-id", "starttime_ticks": 42}
    )
    identity = {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }
    registration: dict[str, object] = {
        "schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL,
        "launch_id": launch.launch_id, "journal_id": launch.journal_id,
        "run_id": launch.run_id, "parent_task_id": launch.parent_task_id,
        "task_id": launch.task_id, "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "consumption_sha256": "c" * 64,
        "executable_identity": _test_digest(identity),
        "owner_identity": owner, "owner_identity_sha256": _test_digest(owner),
        "execution_binding": (
            "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
        ),
        "execution_snapshot_relative_path": (
            ".producer-snapshots/bootstrap" if sys.platform == "darwin" else None
        ),
        "execution_snapshot_sha256": descriptor.bootstrap_sha256,
        "execution_snapshot_size": descriptor.size,
        "target_execution_binding": (
            "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
        ),
        "target_execution_snapshot_relative_path": (
            ".producer-snapshots/target" if sys.platform == "darwin" else None
        ),
        "target_execution_snapshot_sha256": launch.target_executable_identity,
        "target_execution_snapshot_size": 128,
        "pid": 1234, "pgid": 1234,
        "recovery_lock_protocol": "journal-flock-v1",
        "recovery_lock_device": 5, "recovery_lock_inode": 6,
        "gate_protocol": launch.gate_protocol, "registered_at_unix_ns": 7,
        "launch_sha256": launch.launch_sha256,
        "bootstrap_descriptor_sha256": descriptor.descriptor_sha256,
        "target_executable_identity": launch.target_executable_identity,
    }
    registration["registration_sha256"] = _test_digest(registration)
    return launch, descriptor, registration


def _test_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _attempt_records(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    descriptor = _production_descriptor()
    launch = build_trusted_bootstrap_launch(intent, attestation, descriptor, gate_nonce=attestation.nonce)
    claim: dict[str, object] = {
        "schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL,
        "consumption_id": intent.launch_id, "launch_id": intent.launch_id,
        "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "intent_sha256": intent.intent_sha256,
        "attestation_sha256": attestation.attestation_sha256,
        "nonce": attestation.nonce,
        "executable_identity": _test_digest({
            "sha256": intent.executable_sha256, "size": intent.executable_size,
            "device": intent.executable_device, "inode": intent.executable_inode,
            "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
        }),
    }
    claim["consumption_sha256"] = _test_digest(claim)
    _, _, registration = _formal_registration()
    registration.update({
        "intent_sha256": launch.intent_sha256,
        "attestation_sha256": launch.attestation_sha256,
        "consumption_sha256": claim["consumption_sha256"],
        "launch_sha256": launch.launch_sha256,
        "target_executable_identity": launch.target_executable_identity,
        "target_execution_snapshot_sha256": launch.target_executable_identity,
        "target_execution_snapshot_size": intent.executable_size,
    })
    _rehash_record(registration, "registration_sha256")
    evidence = TrustedBootstrapEvidence(
        launch_sha256=launch.launch_sha256,
        registration_sha256=registration["registration_sha256"],
        bootstrap_ready_observed=True, release_observed=True,
        target_started_observed=True, target_start_count=1,
        target_group_identity=_test_digest({"pid": 1235, "pgid": 1234}),
        target_pid=1235, target_pgid=1234,
        pre_gate_target_work_observed=False, status="passed",
    )
    return launch, descriptor, intent, attestation, claim, registration, evidence


def _rehash_record(record: dict[str, object], digest_field: str) -> None:
    record[digest_field] = _test_digest({key: value for key, value in record.items() if key != digest_field})


def _verify_attempt(records: tuple[object, ...], *, evidence: object = ...):
    launch, descriptor, intent, attestation, claim, registration, stored_evidence = records
    supplied_evidence = stored_evidence if evidence is ... else evidence
    if isinstance(supplied_evidence, TrustedBootstrapEvidence):
        supplied_evidence = supplied_evidence.to_dict()
    return verify_trusted_bootstrap_attempt(
        launch, descriptor, intent, attestation, claim, registration,
        evidence=supplied_evidence,
    )


def _write_attempt_records(
    workspace: Path, records: tuple[object, ...], *, evidence: object = ...,
) -> tuple[Path, Path, Path]:
    launch, _, _, attestation, claim, registration, stored_evidence = records
    batch = workspace / "evolution" / "producer-batches" / launch.journal_id
    batch.mkdir(parents=True)
    nonce_key = hashlib.sha256(attestation.nonce.encode("utf-8")).hexdigest()
    ledger = workspace / "evolution" / "producer-nonces" / f"{nonce_key}.json"
    ledger.parent.mkdir(parents=True)

    def write(path: Path, value: object) -> None:
        path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    write(batch / "attestation-consumption.json", claim)
    write(ledger, claim)
    write(batch / "process-registration.json", registration)
    supplied_evidence = stored_evidence if evidence is ... else evidence
    if supplied_evidence is not None:
        write(
            batch / "trusted-bootstrap-evidence.json",
            supplied_evidence.to_dict() if isinstance(supplied_evidence, TrustedBootstrapEvidence) else supplied_evidence,
        )
    return batch, ledger, batch / "process-registration.json"


def _observe_attempt(workspace: Path, records: tuple[object, ...]):
    launch, descriptor, intent, attestation, *_ = records
    return observe_trusted_bootstrap_attempt(
        workspace, launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
    )


def test_attempt_observer_reads_durable_claim_ledger_registration_and_evidence(tmp_path: Path):
    records = _attempt_records(tmp_path)
    _write_attempt_records(tmp_path, records)
    assert _observe_attempt(tmp_path, records) == _verify_attempt(records)


@pytest.mark.parametrize("evidence_kind", ["missing", "unknown"])
def test_attempt_observer_requires_recovery_without_terminal_evidence(tmp_path: Path, evidence_kind: str):
    records = _attempt_records(tmp_path)
    evidence = None
    if evidence_kind == "unknown":
        evidence = TrustedBootstrapEvidence(
            launch_sha256=records[0].launch_sha256,
            registration_sha256=records[5]["registration_sha256"],
            bootstrap_ready_observed=True, release_observed=False,
            target_started_observed=False, target_start_count=0,
            target_group_identity=None, target_pid=None, target_pgid=None,
            pre_gate_target_work_observed=False,
            status="unknown",
        )
    _write_attempt_records(tmp_path, records, evidence=evidence)
    result = _observe_attempt(tmp_path, records)
    assert result["status"] == "recovery_required"
    assert result["reason"] == (
        "trusted_bootstrap_terminal_evidence_missing" if evidence is None else "trusted_bootstrap_evidence_unknown"
    )


def test_attempt_observer_rejects_missing_nonce_ledger(tmp_path: Path):
    records = _attempt_records(tmp_path)
    _, ledger, _ = _write_attempt_records(tmp_path, records)
    ledger.unlink()
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)


@pytest.mark.parametrize("replacement", ["different-claim", "symlink"])
def test_attempt_observer_rejects_replaced_nonce_ledger(tmp_path: Path, replacement: str):
    records = _attempt_records(tmp_path)
    _, ledger, _ = _write_attempt_records(tmp_path, records)
    if replacement == "different-claim":
        forged = dict(records[4])
        forged["journal_id"] = "journal-002"
        _rehash_record(forged, "consumption_sha256")
        ledger.write_bytes(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    else:
        moved = ledger.with_name("held-nonce.json")
        ledger.rename(moved)
        ledger.symlink_to(moved)
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)


@pytest.mark.parametrize("missing_record", ["claim", "registration"])
def test_attempt_observer_rejects_missing_required_record(tmp_path: Path, missing_record: str):
    records = _attempt_records(tmp_path)
    batch, _, registration = _write_attempt_records(tmp_path, records)
    removed = batch / "attestation-consumption.json" if missing_record == "claim" else registration
    removed.unlink()
    with pytest.raises(ProducerBootstrapError) as failure:
        _observe_attempt(tmp_path, records)
    assert failure.value.code == f"producer_bootstrap_attempt_{missing_record}_missing"


def test_attempt_observer_rejects_nonce_directory_replacement_during_read(tmp_path: Path, monkeypatch):
    records = _attempt_records(tmp_path)
    _, ledger, _ = _write_attempt_records(tmp_path, records)
    nonce_directory = ledger.parent
    replacement = nonce_directory.with_name("replacement-nonces")
    replacement.mkdir()
    original_open = os.open
    replaced = False

    def replace_on_ledger_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if not replaced and str(path) == ledger.name:
            replaced = True
            nonce_directory.rename(nonce_directory.with_name("held-nonces"))
            replacement.rename(nonce_directory)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_on_ledger_open)
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)
    assert replaced


@pytest.mark.parametrize("changed_record", ["claim", "registration"])
def test_attempt_observer_rejects_rehashed_record_replacement(tmp_path: Path, changed_record: str):
    records = _attempt_records(tmp_path)
    claim, registration = records[4], records[5]
    if changed_record == "claim":
        claim["executable_identity"] = registration["executable_identity"]
        _rehash_record(claim, "consumption_sha256")
        registration["consumption_sha256"] = claim["consumption_sha256"]
    else:
        registration["executable_identity"] = claim["executable_identity"]
    _rehash_record(registration, "registration_sha256")
    _write_attempt_records(tmp_path, records, evidence=None)
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)


def test_attempt_observer_rejects_symlinked_batch_directory(tmp_path: Path):
    records = _attempt_records(tmp_path)
    batch, _, _ = _write_attempt_records(tmp_path, records)
    moved = batch.with_name("held-batch")
    batch.rename(moved)
    batch.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)


def test_attempt_observer_rejects_batch_directory_replacement_during_read(tmp_path: Path, monkeypatch):
    records = _attempt_records(tmp_path)
    batch, _, _ = _write_attempt_records(tmp_path, records)
    replacement = batch.with_name("replacement-batch")
    replacement.mkdir()
    original_open = os.open
    replaced = False

    def replace_on_registration_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if not replaced and str(path) == "process-registration.json":
            replaced = True
            batch.rename(batch.with_name("held-batch"))
            replacement.rename(batch)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_on_registration_open)
    with pytest.raises(ProducerBootstrapError):
        _observe_attempt(tmp_path, records)
    assert replaced


def test_attempt_observer_has_no_process_or_file_side_effects(tmp_path: Path, monkeypatch):
    records = _attempt_records(tmp_path)
    _write_attempt_records(tmp_path, records)
    files_before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("read-only observation must not launch, signal, or write")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(os, "mkdir", forbidden)
    assert _observe_attempt(tmp_path, records)["status"] == "evidence_available"
    assert files_before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_attempt_verifier_binds_target_claim_bootstrap_registration_and_evidence(tmp_path: Path):
    records = _attempt_records(tmp_path)
    assert records[6].target_pid != records[5]["pid"]
    assert records[6].target_pgid == records[5]["pgid"]
    result = _verify_attempt(records)
    assert result["status"] == "evidence_available"
    assert result["bootstrap_status"] == "passed"
    assert result["registration_sha256"] == records[5]["registration_sha256"]
    assert result["evidence_sha256"] == records[6].evidence_sha256
    assert verify_trusted_bootstrap_attempt(*records) == result


def _native_v2_records(tmp_path: Path):
    from lunar_evolution.native_deadline_binding import NATIVE_CONSUMPTION_PROTOCOL

    records = _attempt_records(tmp_path)
    claim, registration = records[4], records[5]
    claim.update({
        "schema_version": "2", "protocol": NATIVE_CONSUMPTION_PROTOCOL,
        "deadline_binding": {
            "schema_version": "1", "protocol": "lunar-native-deadline-file-binding-v1",
            "name": "native-trusted-attempt-deadline.json",
            "deadline_sha256": "a" * 64, "raw_sha256": "b" * 64,
            "size": 256, "device": 3, "inode": 4, "mode": 0o600,
            "mtime_ns": 5, "ctime_ns": 6,
        },
    })
    _rehash_record(claim, "consumption_sha256")
    registration["consumption_sha256"] = claim["consumption_sha256"]
    _rehash_record(registration, "registration_sha256")
    return records


def test_native_v2_attempt_projects_detached_pin_without_file_authority(tmp_path: Path):
    records = _native_v2_records(tmp_path)
    result = _verify_attempt(records, evidence=None)
    assert result["status"] == "recovery_required"
    assert result["deadline_binding"] == records[4]["deadline_binding"]
    result["deadline_binding"]["inode"] += 1
    assert result["deadline_binding"] != records[4]["deadline_binding"]
    # The pure verifier does not manufacture a legacy pin or require a filesystem.
    (tmp_path / "legacy").mkdir()
    legacy = _attempt_records(tmp_path / "legacy")
    assert "deadline_binding" not in _verify_attempt(legacy, evidence=None)


def test_native_v2_observer_projects_pin_after_comparing_both_claim_files(tmp_path: Path):
    records = _native_v2_records(tmp_path)
    _, ledger, _ = _write_attempt_records(tmp_path, records, evidence=None)
    observed = _observe_attempt(tmp_path, records)
    assert observed == _verify_attempt(records, evidence=None)
    forged = json.loads(ledger.read_bytes())
    forged["deadline_binding"]["inode"] += 1
    _rehash_record(forged, "consumption_sha256")
    ledger.write_bytes(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ProducerBootstrapError) as failure:
        _observe_attempt(tmp_path, records)
    assert failure.value.code == "producer_bootstrap_attempt_nonce_ledger_mismatch"


@pytest.mark.parametrize("encoded", [False, True])
def test_native_v2_attempt_consumption_digest_keeps_independent_registration_pin(tmp_path: Path, encoded: bool):
    records = list(_native_v2_records(tmp_path))
    records[4]["deadline_binding"]["inode"] += 1
    _rehash_record(records[4], "consumption_sha256")
    if encoded:
        records[4] = json.dumps(records[4], sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ProducerBootstrapError) as failure:
        _verify_attempt(tuple(records), evidence=None)
    assert failure.value.code == "producer_bootstrap_attempt_registration_binding_mismatch"


@pytest.mark.parametrize("change", [
    "v1_with_binding", "v2_without_binding", "v2_old_protocol", "v1_new_protocol",
    "extra_field", "missing_field", "bad_pin_type", "pin_extra_field", "pin_bool_inode",
])
def test_native_v2_attempt_requires_exact_schema_and_strict_pin(tmp_path: Path, change: str):
    records = _native_v2_records(tmp_path)
    claim = records[4]
    if change == "v1_with_binding":
        claim.update({"schema_version": "1", "protocol": PRODUCER_PROCESS_PROTOCOL})
    elif change == "v2_without_binding":
        claim.pop("deadline_binding")
    elif change == "v2_old_protocol":
        claim["protocol"] = PRODUCER_PROCESS_PROTOCOL
    elif change == "v1_new_protocol":
        claim["schema_version"] = "1"
    elif change == "extra_field":
        claim["future"] = True
    elif change == "missing_field":
        claim.pop("consumption_id")
    elif change == "bad_pin_type":
        claim["deadline_binding"] = None
    elif change == "pin_extra_field":
        claim["deadline_binding"]["future"] = True
    else:
        claim["deadline_binding"]["inode"] = True
    _rehash_record(claim, "consumption_sha256")
    with pytest.raises(ProducerBootstrapError):
        _verify_attempt(records, evidence=None)


def test_native_v2_attempt_rejects_noncanonical_duplicate_and_oversized_claims(tmp_path: Path):
    records = list(_native_v2_records(tmp_path))
    claim = records[4]
    canonical = json.dumps(claim, sort_keys=True, separators=(",", ":")).encode()
    for encoded in (canonical + b"\n", b'{"schema_version":"2",' + canonical[1:]):
        records[4] = encoded
        with pytest.raises(ProducerBootstrapError):
            _verify_attempt(tuple(records), evidence=None)
    claim["nonce"] = "n" * (64 * 1024)
    records[4] = claim
    with pytest.raises(ProducerBootstrapError) as failure:
        _verify_attempt(tuple(records), evidence=None)
    assert failure.value.code == "producer_bootstrap_payload_too_large"


def test_attempt_verifier_rejects_rehashed_target_snapshot_size_drift(tmp_path: Path):
    records = _attempt_records(tmp_path)
    registration = records[5]
    registration["target_execution_snapshot_size"] += 1
    _rehash_record(registration, "registration_sha256")
    with pytest.raises(ProducerBootstrapError) as exc:
        _verify_attempt(records, evidence=None)
    assert exc.value.code == "producer_bootstrap_attempt_target_binding_mismatch"


def test_attempt_observer_rejects_rehashed_target_snapshot_size_drift(tmp_path: Path):
    records = _attempt_records(tmp_path)
    registration = records[5]
    registration["target_execution_snapshot_size"] += 1
    _rehash_record(registration, "registration_sha256")
    _write_attempt_records(tmp_path, records, evidence=None)
    with pytest.raises(ProducerBootstrapError) as exc:
        _observe_attempt(tmp_path, records)
    assert exc.value.code == "producer_bootstrap_attempt_target_binding_mismatch"


@pytest.mark.parametrize("swapped_field", ["target_claim", "bootstrap_registration"])
def test_attempt_verifier_rejects_rehashed_target_bootstrap_identity_swap(tmp_path: Path, swapped_field: str):
    records = _attempt_records(tmp_path)
    claim, registration = records[4], records[5]
    if swapped_field == "target_claim":
        claim["executable_identity"] = registration["executable_identity"]
        _rehash_record(claim, "consumption_sha256")
        registration["consumption_sha256"] = claim["consumption_sha256"]
    else:
        registration["executable_identity"] = claim["executable_identity"]
    _rehash_record(registration, "registration_sha256")
    with pytest.raises(ProducerBootstrapError):
        _verify_attempt(records, evidence=None)


def test_attempt_verifier_rejects_rehashed_cross_journal_claim(tmp_path: Path):
    records = _attempt_records(tmp_path)
    claim, registration = records[4], records[5]
    claim["journal_id"] = "journal-002"
    _rehash_record(claim, "consumption_sha256")
    registration["consumption_sha256"] = claim["consumption_sha256"]
    _rehash_record(registration, "registration_sha256")
    with pytest.raises(ProducerBootstrapError):
        _verify_attempt(records, evidence=None)


def test_attempt_verifier_rejects_rehashed_evidence_registration_substitution(tmp_path: Path):
    records = _attempt_records(tmp_path)
    forged = records[6].to_dict()
    forged["registration_sha256"] = "d" * 64
    _rehash_record(forged, "evidence_sha256")
    with pytest.raises(ProducerBootstrapError):
        _verify_attempt(records, evidence=forged)


def test_attempt_verifier_rejects_rehashed_target_group_substitution(tmp_path: Path):
    records = _attempt_records(tmp_path)
    forged = records[6].to_dict()
    forged["target_pgid"] = 9999
    forged["target_group_identity"] = _test_digest({"pid": forged["target_pid"], "pgid": 9999})
    _rehash_record(forged, "evidence_sha256")
    with pytest.raises(ProducerBootstrapError) as exc:
        _verify_attempt(records, evidence=forged)
    assert exc.value.code == "producer_bootstrap_attempt_target_group_mismatch"


def test_attempt_observer_rejects_rehashed_target_group_substitution(tmp_path: Path):
    records = _attempt_records(tmp_path)
    forged = records[6].to_dict()
    forged["target_pgid"] = 9999
    forged["target_group_identity"] = _test_digest({"pid": forged["target_pid"], "pgid": 9999})
    _rehash_record(forged, "evidence_sha256")
    _write_attempt_records(tmp_path, records, evidence=forged)
    with pytest.raises(ProducerBootstrapError) as exc:
        _observe_attempt(tmp_path, records)
    assert exc.value.code == "producer_bootstrap_attempt_target_group_mismatch"


def test_attempt_verifier_requires_recovery_for_missing_or_unknown_evidence(tmp_path: Path):
    records = _attempt_records(tmp_path)
    assert _verify_attempt(records, evidence=None)["status"] == "recovery_required"
    unknown = TrustedBootstrapEvidence(
        launch_sha256=records[0].launch_sha256,
        registration_sha256=records[5]["registration_sha256"],
        bootstrap_ready_observed=True, release_observed=False,
        target_started_observed=False, target_start_count=0,
        target_group_identity=None, target_pid=None, target_pgid=None,
        pre_gate_target_work_observed=False,
        status="unknown",
    )
    assert _verify_attempt(records, evidence=unknown)["status"] == "recovery_required"


def test_attempt_verifier_rejects_fixture_only_and_has_no_process_or_file_side_effects(tmp_path: Path, monkeypatch):
    records = _attempt_records(tmp_path)
    files_before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("read-only verifier must not launch or signal a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    assert _verify_attempt(records)["status"] == "evidence_available"
    assert files_before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    fixture_records = (records[0], _descriptor(), *records[2:])
    with pytest.raises(ProducerBootstrapError) as exc:
        _verify_attempt(fixture_records)
    assert exc.value.code == "producer_bootstrap_production_mode_required"


def test_formal_registration_binds_bootstrap_target_and_feature156_owner_lock():
    launch, descriptor, registration = _formal_registration()
    assert verify_trusted_bootstrap_process_registration(launch, descriptor, registration) == registration
    encoded = json.dumps(registration, sort_keys=True, separators=(",", ":"))
    assert verify_trusted_bootstrap_process_registration(launch, descriptor, encoded) == registration


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin snapshot registration")
def test_formal_registration_rejects_ordinary_producer_snapshot_even_when_rehashed():
    launch, descriptor, registration = _formal_registration()
    registration["execution_snapshot_relative_path"] = ".producer-snapshots/executable"
    _rehash_record(registration, "registration_sha256")
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == "producer_bootstrap_process_registration_execution_binding_mismatch"


@pytest.mark.parametrize(
    ("field", "replacement", "code"),
    [
        ("launch_sha256", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("bootstrap_descriptor_sha256", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("target_executable_identity", "d" * 64, "producer_bootstrap_process_registration_binding_mismatch"),
        ("task_id", "other-task", "producer_bootstrap_process_registration_binding_mismatch"),
        ("pid", 1235, "producer_bootstrap_process_registration_process_identity_invalid"),
        ("pgid", 1235, "producer_bootstrap_process_registration_process_identity_invalid"),
        ("owner_identity_sha256", "d" * 64, "producer_bootstrap_process_registration_owner_identity_invalid"),
        ("recovery_lock_inode", 0, "producer_bootstrap_process_registration_lock_identity_invalid"),
        ("execution_snapshot_sha256", "d" * 64, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("execution_snapshot_size", 129, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("target_execution_binding", "pathname_unbound", "producer_bootstrap_process_registration_target_binding_mismatch"),
        ("target_execution_snapshot_relative_path", ".producer-snapshots/executable", "producer_bootstrap_process_registration_target_binding_mismatch"),
        ("target_execution_snapshot_sha256", "d" * 64, "producer_bootstrap_process_registration_target_binding_mismatch"),
        ("target_execution_snapshot_size", 0, "producer_bootstrap_process_registration_target_binding_mismatch"),
        ("executable_identity", "d" * 64, "producer_bootstrap_process_registration_execution_binding_mismatch"),
        ("execution_binding", "pathname_unbound", "producer_bootstrap_process_registration_execution_binding_mismatch"),
    ],
)
def test_formal_registration_rejects_rehashed_identity_drift(field, replacement, code):
    launch, descriptor, registration = _formal_registration()
    registration[field] = replacement
    registration["registration_sha256"] = _test_digest({
        key: value for key, value in registration.items() if key != "registration_sha256"
    })
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == code


def test_formal_registration_rejects_owner_drift_even_with_rehashed_owner():
    launch, descriptor, registration = _formal_registration()
    owner = dict(registration["owner_identity"])
    owner["pid"] = 1235
    registration["owner_identity"] = owner
    registration["owner_identity_sha256"] = _test_digest(owner)
    registration["registration_sha256"] = _test_digest({
        key: value for key, value in registration.items() if key != "registration_sha256"
    })
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == "producer_bootstrap_process_registration_owner_identity_invalid"


def test_formal_registration_rejects_fixture_descriptor_and_tampered_self_digest():
    launch, descriptor, registration = _formal_registration()
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, _descriptor(), registration)
    assert exc.value.code == "producer_bootstrap_production_mode_required"

    registration["registered_at_unix_ns"] = 8
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, registration)
    assert exc.value.code == "producer_bootstrap_process_registration_digest_mismatch"


def test_formal_registration_rejects_missing_fields_and_noncanonical_encoding():
    launch, descriptor, registration = _formal_registration()
    missing = dict(registration)
    del missing["recovery_lock_device"]
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, missing)
    assert exc.value.code == "producer_bootstrap_process_registration_schema_invalid"

    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_process_registration(launch, descriptor, json.dumps(registration, indent=2))
    assert exc.value.code == "producer_bootstrap_process_registration_noncanonical"


def test_launch_adapter_rejects_fixture_only_mode(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, attestation, _descriptor(), gate_nonce="nonce-001")
    assert exc.value.code == "producer_bootstrap_production_mode_required"


def test_launch_adapter_binds_verified_intent_and_attestation(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    launch = build_trusted_bootstrap_launch(
        intent, attestation, _production_descriptor(), gate_nonce="nonce-001",
    )
    assert launch.intent_sha256 == intent.intent_sha256
    assert launch.attestation_sha256 == attestation.attestation_sha256
    assert launch.target_executable_identity == intent.executable_sha256


def test_launch_adapter_rejects_attestation_drift(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    forged = dict(attestation.to_dict())
    forged["intent_sha256"] = "b" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, forged, _production_descriptor(), gate_nonce="nonce-001")
    assert exc.value.code == "producer_bootstrap_launch_attestation_invalid"


def test_launch_adapter_rejects_gate_nonce_drift(tmp_path: Path):
    intent, attestation = _producer_admission(tmp_path)
    with pytest.raises(ProducerBootstrapError) as exc:
        build_trusted_bootstrap_launch(intent, attestation, _production_descriptor(), gate_nonce="nonce-002")
    assert exc.value.code == "producer_bootstrap_gate_nonce_mismatch"


def _ready(launch: TrustedBootstrapLaunch) -> BootstrapHandshakeFrame:
    return BootstrapHandshakeFrame(
        sequence=1,
        kind="bootstrap_ready",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )


def _started(launch: TrustedBootstrapLaunch) -> BootstrapHandshakeFrame:
    return BootstrapHandshakeFrame(
        sequence=2,
        kind="target_started",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
        target_executable_identity=launch.target_executable_identity,
        observed_pid=1234,
        observed_pgid=1234,
    )


def test_descriptor_and_launch_have_stable_self_digests():
    descriptor = _descriptor()
    launch = _launch()
    assert descriptor.descriptor_sha256 == descriptor.digest()
    assert launch.launch_sha256 == launch.digest()


def test_registration_binds_launch_and_process_identity_with_stable_digest():
    launch = _launch()
    registration = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234)
    assert isinstance(registration, TrustedBootstrapRegistration)
    assert registration.registration_sha256 == registration.digest()
    assert verify_trusted_bootstrap_registration(launch, registration.to_dict()) == registration

    encoded = json.dumps(registration.to_dict(), sort_keys=True, separators=(",", ":"))
    assert parse_trusted_bootstrap_registration(encoded, launch=launch) == registration


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("launch_id", "producer_bootstrap_registration_binding_mismatch"),
        ("intent_sha256", "producer_bootstrap_registration_binding_mismatch"),
        ("bootstrap_descriptor_sha256", "producer_bootstrap_registration_binding_mismatch"),
        ("target_executable_identity", "producer_bootstrap_registration_binding_mismatch"),
    ],
)
def test_registration_rejects_launch_identity_drift(field: str, code: str):
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value[field] = "d" * 64 if field.endswith("sha256") or field == "target_executable_identity" else "other-launch"
    value["registration_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        verify_trusted_bootstrap_registration(launch, value)
    assert exc.value.code == code


def test_registration_rejects_noncanonical_or_digest_tampering():
    launch = _launch()
    registration = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234)
    encoded = json.dumps(registration.to_dict(), indent=2)
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(encoded)
    assert exc.value.code == "producer_bootstrap_registration_noncanonical"

    forged = registration.to_dict()
    forged["pid"] = 4321
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(forged)
    assert exc.value.code == "producer_bootstrap_registration_digest_mismatch"


@pytest.mark.parametrize("field", ["pid", "pgid"])
def test_registration_rejects_invalid_process_identity(field: str):
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value[field] = True
    value["registration_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(value)
    assert exc.value.code == "producer_bootstrap_registration_process_identity_invalid"


def test_trusted_bootstrap_happy_path_produces_passed_evidence():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    assert session.evidence().status == "unknown"
    session.record_eof()
    evidence = session.evidence()
    assert evidence.status == "passed"
    assert evidence.release_observed is True
    assert evidence.target_start_count == 1
    assert (evidence.target_pid, evidence.target_pgid) == (1234, 1234)
    assert evidence.evidence_sha256 == evidence.digest()


def test_evidence_parser_requires_canonical_self_authenticating_payload():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    session.record_eof()
    evidence = session.evidence()

    encoded = json.dumps(evidence.to_dict(), sort_keys=True, separators=(",", ":"))
    assert parse_trusted_bootstrap_evidence(encoded) == evidence

    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(json.dumps(evidence.to_dict(), indent=2))
    assert exc.value.code == "producer_bootstrap_evidence_noncanonical"

    forged = evidence.to_dict()
    forged["target_group_identity"] = "d" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(forged)
    assert exc.value.code == "producer_bootstrap_target_group_identity_mismatch"

    missing_digest = evidence.to_dict()
    missing_digest["evidence_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(missing_digest)
    assert exc.value.code == "producer_bootstrap_evidence_digest_invalid"
    forged["evidence_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        TrustedBootstrapEvidence(**forged)
    assert exc.value.code == "producer_bootstrap_target_group_identity_mismatch"

    for field in ("target_pid", "target_pgid"):
        missing = evidence.to_dict()
        del missing[field]
        with pytest.raises(ProducerBootstrapError) as exc:
            parse_trusted_bootstrap_evidence(missing)
        assert exc.value.code == "producer_bootstrap_evidence_schema_invalid"

    forged = evidence.to_dict()
    forged["target_pgid"] = 9999
    _rehash_record(forged, "evidence_sha256")
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_evidence(forged)
    assert exc.value.code == "producer_bootstrap_target_group_identity_mismatch"


def test_registration_parser_rejects_missing_digest_for_persisted_payload():
    launch = _launch()
    value = build_trusted_bootstrap_registration(launch, pid=1234, pgid=1234).to_dict()
    value["registration_sha256"] = None

    with pytest.raises(ProducerBootstrapError) as exc:
        parse_trusted_bootstrap_registration(value, launch=launch)
    assert exc.value.code == "producer_bootstrap_registration_digest_invalid"


def test_terminal_frame_after_target_start_keeps_passed_evidence():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    terminal = BootstrapHandshakeFrame(
        sequence=3,
        kind="terminal",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )
    session.accept_frame(terminal)
    evidence = session.evidence()
    assert evidence.status == "passed"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is True
    with pytest.raises(ProducerBootstrapError) as exc:
        session.release("nonce-001")
    assert exc.value.code == "producer_bootstrap_terminal"
    assert session.evidence().status == "passed"


def test_terminal_frame_before_target_start_is_failed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    terminal = BootstrapHandshakeFrame(
        sequence=3,
        kind="terminal",
        launch_sha256=launch.launch_sha256 or launch.digest(),
        intent_sha256=launch.intent_sha256,
    )
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(terminal)
    assert exc.value.code == "producer_bootstrap_terminal_order_invalid"
    evidence = session.evidence()
    assert evidence.status == "failed"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is False


@pytest.mark.parametrize(
    ("action", "code"),
    [
        ("wrong_token", "producer_bootstrap_release_token_invalid"),
        ("duplicate_release", "producer_bootstrap_duplicate_release"),
        ("early_target", "producer_bootstrap_target_started_before_release"),
        ("pre_gate_work", "producer_bootstrap_pre_gate_work"),
    ],
)
def test_invalid_order_is_terminal_and_never_passes(action: str, code: str):
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        if action == "wrong_token":
            session.release("wrong")
        elif action == "duplicate_release":
            session.release("nonce-001")
            session.release("nonce-001")
        elif action == "early_target":
            session.accept_frame(_started(launch))
        else:
            session.record_pre_gate_target_work()
    assert exc.value.code == code
    assert session.evidence().status == "failed"


def test_duplicate_target_start_and_identity_drift_fail_closed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(_started(launch))
    assert exc.value.code == "producer_bootstrap_duplicate_target_start"

    other = TrustedBootstrapSession(launch, "c" * 64)
    other.accept_frame(_ready(launch))
    other.release("nonce-001")
    altered = _started(launch).to_dict()
    altered["target_executable_identity"] = "d" * 64
    altered["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        other.accept_frame(parse_bootstrap_handshake_frame(altered))
    assert exc.value.code == "producer_bootstrap_target_identity_mismatch"


def test_frame_parser_rejects_duplicate_keys_and_tampering():
    launch = _launch()
    frame = _ready(launch).to_dict()
    duplicate = json.dumps(frame).replace('"kind": "bootstrap_ready"', '"kind": "bootstrap_ready", "kind": "bootstrap_ready"')
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(duplicate)
    assert exc.value.code == "producer_bootstrap_duplicate_key"

    frame["intent_sha256"] = "e" * 64
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(frame)
    assert exc.value.code == "producer_bootstrap_digest_mismatch"


def test_session_malformed_or_unbound_frame_is_failed_not_unknown():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame('{"kind":"bootstrap_ready"}')
    assert exc.value.code == "producer_bootstrap_frame_schema_invalid"
    assert session.evidence().status == "failed"

    other = TrustedBootstrapSession(launch, "c" * 64)
    unbound = _ready(launch).to_dict()
    unbound["launch_sha256"] = "d" * 64
    unbound["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        other.accept_frame(unbound)
    assert exc.value.code == "producer_bootstrap_frame_binding_mismatch"
    assert other.evidence().status == "failed"


def test_ready_without_release_is_unknown_and_does_not_claim_success():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    evidence = session.evidence()
    assert evidence.status == "unknown"
    assert evidence.bootstrap_ready_observed is True
    assert evidence.target_started_observed is False


def test_early_target_failure_does_not_claim_ready_observed():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    with pytest.raises(ProducerBootstrapError) as exc:
        session.accept_frame(_started(launch))
    assert exc.value.code == "producer_bootstrap_target_started_before_release"
    evidence = session.evidence()
    assert evidence.status == "failed"
    assert evidence.bootstrap_ready_observed is False


def test_eof_before_target_start_is_terminal_failure():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    with pytest.raises(ProducerBootstrapError) as exc:
        session.record_eof()
    assert exc.value.code == "producer_bootstrap_early_eof"
    assert session.evidence().status == "failed"


def test_eof_after_target_start_is_successful_handshake_close():
    launch = _launch()
    session = TrustedBootstrapSession(launch, "c" * 64)
    session.accept_frame(_ready(launch))
    session.release("nonce-001")
    session.accept_frame(_started(launch))
    assert session.evidence().status == "unknown"
    session.record_eof()
    assert session.evidence().status == "passed"


def test_non_target_frames_cannot_carry_process_identity():
    launch = _launch()
    frame = _ready(launch).to_dict()
    frame["observed_pid"] = 1234
    frame["frame_sha256"] = None
    with pytest.raises(ProducerBootstrapError) as exc:
        parse_bootstrap_handshake_frame(frame)
    assert exc.value.code == "producer_bootstrap_target_frame_invalid"
