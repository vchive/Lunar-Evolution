"""Original deadline authority survives missing-terminal and cleanup recovery.

All targets are local inert C fixtures. Recovery signal ordering uses mocked OS
probes and signals, so none of these tests can signal an unrelated process.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

import pytest
from test_native_trusted_attempt import _attempt

import lunar_evolution.native_trusted_attempt as runner
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch
from lunar_evolution.producer_process import PRODUCER_PROCESS_PROTOCOL, ProducerProcessError
from lunar_evolution.trusted_bootstrap_handoff import (
    build_trusted_bootstrap_process_registration_handoff,
)

pytestmark = pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform",
)

_DEADLINE = "native-trusted-attempt-deadline.json"
_TERMINAL = "native-trusted-process-terminal.json"
_RECOVERY = "native-trusted-process-recovery.json"
_CLAIM = "attestation-consumption.json"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _rehash(value: dict[str, object], field: str) -> dict[str, object]:
    value[field] = hashlib.sha256(_canonical({k: v for k, v in value.items() if k != field})).hexdigest()
    return value


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_bytes())


def _recover(context, *, cleanup=False):
    workspace, _producer_root, intent, attestation, artifact, _batch = context
    return runner.recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=cleanup,
    )


def _run(context, **kwargs):
    workspace, producer_root, intent, attestation, artifact, _batch = context
    return runner.run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, **kwargs,
    )


def _leave_missing_terminal(context, monkeypatch, **kwargs):
    original = runner._atomic_json

    def fail_terminal(path, value, *, exclusive=False):
        if path.name == _TERMINAL:
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original(path, value, exclusive=exclusive)

    with monkeypatch.context() as patch:
        patch.setattr(runner, "_atomic_json", fail_terminal)
        result = _run(context, **kwargs)
    assert result.reason == "native_trusted_attempt_terminal_write_unknown"
    assert result.terminal_sha256 is None
    assert not (context[-1] / _TERMINAL).exists()
    return result


@pytest.fixture
def unknown_attempt(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    _leave_missing_terminal(context, monkeypatch)
    return context


def _forbid_recovery_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("drifted or legacy recovery attempted cleanup or evidence publication")

    monkeypatch.setattr(runner, "cleanup_registered_process", forbidden)
    monkeypatch.setattr(runner, "_atomic_json", forbidden)


def _mutate_deadline(path: Path, kind: str) -> None:
    raw = path.read_bytes()
    if kind in {"extend", "shrink", "start"}:
        record = json.loads(raw)
        if kind == "extend":
            record["deadline_monotonic"] += 30.0
        elif kind == "shrink":
            record["deadline_monotonic"] = (
                record["started_monotonic"] + record["deadline_monotonic"]
            ) / 2.0
        else:
            record["started_monotonic"] -= 1.0
        path.write_bytes(_canonical(_rehash(record, "deadline_sha256")))
    elif kind == "whitespace":
        path.write_bytes(raw + b"\n")
    elif kind == "inode":
        replacement = path.with_name("deadline-replacement.json")
        replacement.write_bytes(raw)
        assert replacement.stat().st_ino != path.stat().st_ino
        os.replace(replacement, path)
    elif kind == "mode":
        path.chmod(stat.S_IMODE(path.stat().st_mode) ^ 0o100)
    elif kind == "mtime":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    elif kind == "hardlink":
        os.link(path, path.with_name("deadline-alias.json"))
    elif kind == "symlink":
        retained = path.with_name("deadline-retained.json")
        path.rename(retained)
        path.symlink_to(retained.name)
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif kind == "directory":
        path.unlink()
        path.mkdir()
    else:  # pragma: no cover - test parameter contract.
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", [
    "extend", "shrink", "start", "whitespace", "inode", "mode", "mtime",
    "hardlink", "symlink", "fifo", "directory",
])
def test_missing_terminal_recovery_rejects_original_deadline_drift(
    unknown_attempt, monkeypatch, kind,
):
    batch = unknown_attempt[-1]
    _mutate_deadline(batch / _DEADLINE, kind)
    _forbid_recovery_effects(monkeypatch)
    for cleanup in (False, True):
        with pytest.raises(runner.NativeTrustedAttemptError) as failure:
            _recover(unknown_attempt, cleanup=cleanup)
        assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert not (batch / _RECOVERY).exists()


def test_v2_admission_freezes_deadline_before_spawn(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    workspace, _producer_root, _intent, attestation, _artifact, batch = context
    original_spawn = runner.subprocess.Popen
    observed_claims = []

    class CheckedPopen(original_spawn):
        def __init__(self, *args, **kwargs):
            deadline_raw = (batch / _DEADLINE).read_bytes()
            info = (batch / _DEADLINE).stat()
            claim_raw = (batch / _CLAIM).read_bytes()
            claim = json.loads(claim_raw)
            ledger = workspace / "evolution" / "producer-nonces" / (
                hashlib.sha256(attestation.nonce.encode()).hexdigest() + ".json"
            )
            assert ledger.read_bytes() == claim_raw
            assert claim["schema_version"] == "2"
            assert claim["protocol"] == "lunar-native-trusted-attestation-consumption-v2"
            binding = claim["deadline_binding"]
            assert set(binding) == {
                "schema_version", "protocol", "name", "deadline_sha256", "raw_sha256",
                "size", "device", "inode", "mode", "mtime_ns", "ctime_ns",
            }
            assert binding["schema_version"] == "1"
            assert binding["protocol"] == "lunar-native-deadline-file-binding-v1"
            assert binding["name"] == _DEADLINE
            assert binding["deadline_sha256"] == json.loads(deadline_raw)["deadline_sha256"]
            assert binding["raw_sha256"] == hashlib.sha256(deadline_raw).hexdigest()
            assert binding["size"] == len(deadline_raw) == info.st_size
            assert binding["device"] == info.st_dev
            assert binding["inode"] == info.st_ino
            assert binding["mode"] & 0o777 == stat.S_IMODE(info.st_mode)
            assert binding["mtime_ns"] == info.st_mtime_ns
            assert binding["ctime_ns"] == info.st_ctime_ns
            observed_claims.append(claim)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", CheckedPopen)
    result = _run(context)
    assert observed_claims
    assert result.terminal_sha256 is not None
    registration = _read(batch / "process-registration.json")
    assert registration["consumption_sha256"] == observed_claims[0]["consumption_sha256"]
    assert _recover(context)["terminal_sha256"] == result.terminal_sha256


def test_v2_unknown_cleanup_receipt_binds_original_deadline(unknown_attempt):
    batch = unknown_attempt[-1]
    claim = _read(batch / _CLAIM)
    assert _recover(unknown_attempt)["reason"] == "native_trusted_attempt_terminal_receipt_missing"
    receipt = _recover(unknown_attempt, cleanup=True)
    assert receipt["schema_version"] == "2"
    assert receipt["protocol"] == "lunar-native-trusted-process-recovery-v2"
    assert receipt["execution_outcome"] == "unknown"
    assert receipt["consumption_sha256"] == claim["consumption_sha256"]
    assert receipt["deadline_sha256"] == claim["deadline_binding"]["deadline_sha256"]
    assert receipt["deadline_binding_sha256"] == hashlib.sha256(
        _canonical(claim["deadline_binding"]),
    ).hexdigest()
    before = (batch / _RECOVERY).read_bytes(), (batch / _RECOVERY).stat().st_ino
    assert _recover(unknown_attempt) == receipt
    assert ((batch / _RECOVERY).read_bytes(), (batch / _RECOVERY).stat().st_ino) == before


def test_existing_recovery_receipt_replay_revalidates_original_inode(unknown_attempt, monkeypatch):
    batch = unknown_attempt[-1]
    _recover(unknown_attempt, cleanup=True)
    original_receipt = (batch / _RECOVERY).read_bytes()
    _mutate_deadline(batch / _DEADLINE, "inode")
    _forbid_recovery_effects(monkeypatch)
    for cleanup in (False, True):
        with pytest.raises(runner.NativeTrustedAttemptError) as failure:
            _recover(unknown_attempt, cleanup=cleanup)
        assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert (batch / _RECOVERY).read_bytes() == original_receipt


def test_unknown_cleanup_consumes_original_parent_deadline(tmp_path, monkeypatch):
    context = _attempt(tmp_path, timeout=20)
    parent_deadline = time.monotonic() + 6.0
    _leave_missing_terminal(context, monkeypatch, parent_deadline=parent_deadline)
    batch = context[-1]
    record = _read(batch / _DEADLINE)
    assert record["deadline_monotonic"] == parent_deadline
    assert record["deadline_monotonic"] < record["started_monotonic"] + 20.0
    cleanup_deadlines = []

    def observed_cleanup(process, **kwargs):
        cleanup_deadlines.append(kwargs["deadline"])
        return ProcessCleanupResult(
            label=process.label, pid=process.pid, pgid=process.pgid,
            status=ProcessCleanupStatus.ALREADY_EXITED,
        )

    def no_budget_remap(*_args, **_kwargs):
        pytest.fail("unknown recovery recomputed the original admission budget")

    monkeypatch.setattr(runner, "cleanup_registered_process", observed_cleanup)
    monkeypatch.setattr(runner, "_compose_attempt_budget", no_budget_remap)
    monkeypatch.setattr(runner, "_native_guard_deadline", no_budget_remap)
    receipt = _recover(context, cleanup=True)
    assert receipt["execution_outcome"] == "unknown"
    assert cleanup_deadlines == [parent_deadline]


def _downgrade_retained_chain(context):
    """Materialize an exact older chain without adding new deadline authority."""
    workspace, _producer_root, intent, attestation, artifact, batch = context
    claim = _read(batch / _CLAIM)
    claim.pop("deadline_binding")
    claim.update(schema_version="1", protocol=PRODUCER_PROCESS_PROTOCOL)
    _rehash(claim, "consumption_sha256")
    claim_raw = _canonical(claim)
    (batch / _CLAIM).write_bytes(claim_raw)
    ledger = workspace / "evolution" / "producer-nonces" / (
        hashlib.sha256(attestation.nonce.encode()).hexdigest() + ".json"
    )
    ledger.write_bytes(claim_raw)
    registration = _read(batch / "process-registration.json")
    registration["consumption_sha256"] = claim["consumption_sha256"]
    _rehash(registration, "registration_sha256")
    (batch / "process-registration.json").write_bytes(_canonical(registration))
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    handoff = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=artifact.descriptor, intent=intent,
        attestation=attestation, consumption=claim, registration=registration,
    )
    (batch / "trusted-bootstrap-handoff.json").write_bytes(_canonical(handoff))
    evidence = _read(batch / "trusted-bootstrap-evidence.json")
    evidence["registration_sha256"] = registration["registration_sha256"]
    _rehash(evidence, "evidence_sha256")
    (batch / "trusted-bootstrap-evidence.json").write_bytes(_canonical(evidence))
    cleanup = _read(batch / "native-trusted-cleanup.json")
    cleanup["registration_sha256"] = registration["registration_sha256"]
    _rehash(cleanup, "cleanup_sha256")
    (batch / "native-trusted-cleanup.json").write_bytes(_canonical(cleanup))
    if (batch / _TERMINAL).exists():
        terminal = _read(batch / _TERMINAL)
        terminal.update(
            consumption_sha256=claim["consumption_sha256"],
            registration_sha256=registration["registration_sha256"],
            previous_receipt_sha256=registration["registration_sha256"],
            handoff_sha256=handoff["handoff_sha256"],
            bootstrap_evidence_sha256=evidence["evidence_sha256"],
            cleanup_sha256=cleanup["cleanup_sha256"], stream_capture_sha256=None,
        )
        _rehash(terminal, "terminal_sha256")
        (batch / _TERMINAL).write_bytes(_canonical(terminal))


def test_legacy_complete_terminal_retains_readonly_diagnostic(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    _run(context)
    _downgrade_retained_chain(context)
    terminal = _read(context[-1] / _TERMINAL)
    _forbid_recovery_effects(monkeypatch)
    assert _recover(context) == terminal
    assert _recover(context, cleanup=True) == terminal
    assert not (context[-1] / _RECOVERY).exists()


def test_legacy_missing_terminal_has_no_new_cleanup_authority(unknown_attempt, monkeypatch):
    _downgrade_retained_chain(unknown_attempt)
    _forbid_recovery_effects(monkeypatch)
    observed = _recover(unknown_attempt)
    assert observed["status"] == "recovery_required"
    assert observed["reason"] == "native_trusted_recovery_legacy_deadline_unanchored"
    with pytest.raises(runner.NativeTrustedAttemptError) as failure:
        _recover(unknown_attempt, cleanup=True)
    assert failure.value.code == "native_trusted_recovery_legacy_deadline_unanchored"
    assert not (unknown_attempt[-1] / _RECOVERY).exists()


@pytest.mark.parametrize("change", ["remove_binding", "protocol", "schema_version", "v1"])
def test_v2_claim_drift_cannot_downgrade_to_legacy_cleanup(unknown_attempt, monkeypatch, change):
    workspace, _producer_root, _intent, attestation, _artifact, batch = unknown_attempt
    claim = _read(batch / _CLAIM)
    if change in {"remove_binding", "v1"}:
        claim.pop("deadline_binding")
    if change in {"protocol", "v1"}:
        claim["protocol"] = PRODUCER_PROCESS_PROTOCOL
    if change in {"schema_version", "v1"}:
        claim["schema_version"] = "1"
    _rehash(claim, "consumption_sha256")
    raw = _canonical(claim)
    (batch / _CLAIM).write_bytes(raw)
    ledger = workspace / "evolution" / "producer-nonces" / (
        hashlib.sha256(attestation.nonce.encode()).hexdigest() + ".json"
    )
    ledger.write_bytes(raw)
    _forbid_recovery_effects(monkeypatch)
    for cleanup in (False, True):
        with pytest.raises(runner.NativeTrustedAttemptError):
            _recover(unknown_attempt, cleanup=cleanup)
    assert not (batch / _RECOVERY).exists()


def test_deadline_inode_drift_after_registration_keeps_gate_closed(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    batch = context[-1]
    original_publish = runner.publish_trusted_bootstrap_registration
    publications = []

    def drift_after_publish(*args, **kwargs):
        published = original_publish(*args, **kwargs)
        _mutate_deadline(batch / _DEADLINE, "inode")
        publications.append(published)
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", drift_after_publish)
    result = _run(context)
    assert publications
    assert result.status == "recovery_required"
    assert result.gate_released is False
    assert result.target_started is False
    assert result.terminal_sha256 is None
    assert not (batch / "work" / "marker").exists()
    assert (batch / _CLAIM).exists()
    assert not (batch / _TERMINAL).exists()


def test_deadline_drift_during_spawn_stops_before_control_delivery(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    batch = context[-1]
    original_spawn = runner.subprocess.Popen
    children = []

    class DriftingPopen(original_spawn):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            children.append(self)
            _mutate_deadline(batch / _DEADLINE, "inode")

    def forbidden_control(*_args, **_kwargs):
        pytest.fail("spawn-time deadline drift reached native control delivery")

    monkeypatch.setattr(runner.subprocess, "Popen", DriftingPopen)
    monkeypatch.setattr(runner, "_write_attempt_control", forbidden_control)
    result = _run(context)
    assert len(children) == 1
    assert children[0].poll() is not None
    assert result.status == "recovery_required"
    assert result.gate_released is False
    assert result.target_started is False
    assert result.terminal_sha256 is None
    assert not (batch / "work" / "marker").exists()
    assert not (batch / "process-registration.json").exists()
    assert not (batch / _TERMINAL).exists()


def test_deadline_drift_during_gate_write_retains_release_side_effect(tmp_path, monkeypatch):
    context = _attempt(tmp_path)
    batch = context[-1]
    original_write = runner.os.write
    gate_writes = []

    def drift_during_gate_write(fd, data):
        count = original_write(fd, data)
        if data == b"1":
            gate_writes.append(count)
            _mutate_deadline(batch / _DEADLINE, "inode")
        return count

    monkeypatch.setattr(runner.os, "write", drift_during_gate_write)
    result = _run(context)
    assert gate_writes == [1]
    assert result.status == "recovery_required"
    assert result.gate_released is True
    assert result.terminal_sha256 is None
    assert not (batch / _TERMINAL).exists()


def test_unknown_cleanup_requires_complete_registration_handoff(unknown_attempt, monkeypatch):
    batch = unknown_attempt[-1]
    (batch / "trusted-bootstrap-handoff.json").unlink()
    _forbid_recovery_effects(monkeypatch)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _recover(unknown_attempt, cleanup=True)
    assert not (batch / _RECOVERY).exists()


def test_deadline_drift_after_term_prevents_kill_and_trusted_recovery_receipt(
    unknown_attempt, monkeypatch,
):
    import lunar_evolution.process_ownership as ownership

    batch = unknown_attempt[-1]
    registration = _read(batch / "process-registration.json")
    signals = []

    def fake_signal(pgid, sig):
        assert pgid == registration["pgid"]
        signals.append(sig)
        if sig == signal.SIGTERM:
            _mutate_deadline(batch / _DEADLINE, "inode")

    monkeypatch.setattr(ownership, "_group_alive", lambda _pgid: True)
    monkeypatch.setattr(ownership.os, "getpgid", lambda _pid: registration["pgid"])
    monkeypatch.setattr(ownership.os, "killpg", fake_signal)
    monkeypatch.setattr(runner, "_process_owner_identity", lambda _pid: registration["owner_identity"])
    with pytest.raises(runner.NativeTrustedAttemptError) as failure:
        _recover(unknown_attempt, cleanup=True)
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert signals == [signal.SIGTERM]
    assert not (batch / _RECOVERY).exists()


def test_owner_identity_observation_drift_prevents_first_cleanup_signal(
    unknown_attempt, monkeypatch,
):
    import lunar_evolution.process_ownership as ownership

    batch = unknown_attempt[-1]
    registration = _read(batch / "process-registration.json")
    observations = []
    signals = []

    def drift_during_identity(pid):
        assert pid == registration["pid"]
        observations.append(pid)
        _mutate_deadline(batch / _DEADLINE, "inode")
        return registration["owner_identity"]

    monkeypatch.setattr(ownership, "_group_alive", lambda _pgid: True)
    monkeypatch.setattr(ownership.os, "getpgid", lambda _pid: registration["pgid"])
    monkeypatch.setattr(ownership.os, "killpg", lambda _pgid, sig: signals.append(sig))
    monkeypatch.setattr(runner, "_process_owner_identity", drift_during_identity)
    with pytest.raises(runner.NativeTrustedAttemptError) as failure:
        _recover(unknown_attempt, cleanup=True)
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert observations
    assert signals == []
    assert not (batch / _RECOVERY).exists()


def test_matching_boot_observation_cannot_hide_deadline_inode_drift(
    unknown_attempt, monkeypatch,
):
    batch = unknown_attempt[-1]
    boot_id = _read(batch / _DEADLINE)["boot_id"]
    observations = []

    def drift_during_boot_observation():
        observations.append(boot_id)
        _mutate_deadline(batch / _DEADLINE, "inode")
        return boot_id

    monkeypatch.setattr(runner, "_producer_boot_id", drift_during_boot_observation)
    _forbid_recovery_effects(monkeypatch)
    for cleanup in (False, True):
        with pytest.raises(runner.NativeTrustedAttemptError) as failure:
            _recover(unknown_attempt, cleanup=cleanup)
        assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert observations
    assert not (batch / _RECOVERY).exists()


def test_deadline_drift_after_already_exited_cleanup_cannot_publish_receipt(
    unknown_attempt, monkeypatch,
):
    batch = unknown_attempt[-1]

    def drifted_observation(process, **_kwargs):
        _mutate_deadline(batch / _DEADLINE, "inode")
        return ProcessCleanupResult(
            label=process.label, pid=process.pid, pgid=process.pgid,
            status=ProcessCleanupStatus.ALREADY_EXITED,
        )

    monkeypatch.setattr(runner, "cleanup_registered_process", drifted_observation)
    with pytest.raises(runner.NativeTrustedAttemptError) as failure:
        _recover(unknown_attempt, cleanup=True)
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    assert not (batch / _RECOVERY).exists()


def test_partial_v2_consumption_retains_original_deadline_and_never_retries_spawn(
    tmp_path, monkeypatch,
):
    import lunar_evolution.trusted_bootstrap_registration as registration_publisher

    context = _attempt(tmp_path)
    workspace, _producer_root, _intent, attestation, _artifact, batch = context
    original_atomic_json = registration_publisher._atomic_json

    def fail_batch_claim(path, value, *, exclusive=False):
        if path.name == _CLAIM:
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_atomic_json(path, value, exclusive=exclusive)

    def forbidden_spawn(*_args, **_kwargs):
        pytest.fail("partially consumed native attempt spawned its target")

    monkeypatch.setattr(registration_publisher, "_atomic_json", fail_batch_claim)
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden_spawn)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _run(context)
    ledger = workspace / "evolution" / "producer-nonces" / (
        hashlib.sha256(attestation.nonce.encode()).hexdigest() + ".json"
    )
    assert ledger.exists()
    assert not (batch / _CLAIM).exists()
    claim = _read(ledger)
    assert claim["schema_version"] == "2"
    assert claim["deadline_binding"]["raw_sha256"] == hashlib.sha256(
        (batch / _DEADLINE).read_bytes(),
    ).hexdigest()
    before = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in (ledger, batch / _DEADLINE)
    }
    with pytest.raises(runner.NativeTrustedAttemptError):
        _run(context)
    assert all((path.read_bytes(), path.stat().st_ino) == retained for path, retained in before.items())
    assert not (batch / _CLAIM).exists()
    assert not (batch / "process-registration.json").exists()
    assert not (batch / _RECOVERY).exists()
