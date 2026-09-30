from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import (
    ProducerProcessError,
    build_producer_launch_attestation,
    build_producer_launch_intent,
    producer_process,
    run_producer_process,
)
from lunar_evolution.linux_executable_binding import LinuxExecutableBindingError
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_process import recover_producer_process

DIGEST = "a" * 64


def _fixture(tmp_path: Path, *, mode: str = "success"):
    producer_root = tmp_path / "producer-root"
    producer_root.mkdir()
    script = producer_root / "producer.py"
    descendant_setup = ""
    if mode in {"descendant-pipes", "descendant-redirect", "descendant-stubborn"}:
        child_code = "import time; time.sleep(60)"
        if mode == "descendant-stubborn":
            child_code = (
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "open('../ready', 'w').close(); time.sleep(60)"
            )
        kwargs = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if mode == "descendant-redirect" else ""
        descendant_setup = f"subprocess.Popen([sys.executable, '-c', {child_code!r}]{kwargs})\n"
        if mode == "descendant-stubborn":
            descendant_setup += "while not pathlib.Path('../ready').exists(): import time; time.sleep(0.01)\n"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, subprocess, sys\n"
        + ("import time\n"
           "while not pathlib.Path('../exit-before-gate').exists(): time.sleep(0.01)\n"
           "sys.exit(7)\n" if mode == "exit-before-gate" else "")
        + ("pathlib.Path('../pre-gate-side-effect').write_text('hostile', encoding='utf-8')\n"
           if mode == "hostile-pre-gate" else "")
        + "fd = int(os.environ['LUNAR_PRODUCER_GATE_FD'])\n"
        "if os.read(fd, 1) != b'1': sys.exit(4)\n"
        + ("registration = json.loads(pathlib.Path('../process-registration.json').read_text())\n"
           "if registration['pid'] != os.getpid() or registration['pgid'] != os.getpgrp(): sys.exit(5)\n"
           if mode == "gate-order" else "")
        + ("print('x' * 10000)\n" if mode == "overflow" else "")
        + ("os.write(1, b'x' * 131072); os.write(2, b'y' * 131072)\n"
           if mode == "dual-overflow" else "")
        + ("sys.exit(3)\n" if mode == "failed" else "")
        + (f"pathlib.Path('../output/producer-result.json').write_text(json.dumps({{'schema_version':'1','producer_id':'fixture','producer_fingerprint':'{DIGEST}','producer_run_id':'run-1','status':'completed','contract_sha256':'{DIGEST}','budget':{{'requests':{3 if mode == 'over-requests' else 1}}},'materials':[]}}))\n" if mode in {"success", "gate-order", "hostile-pre-gate", "over-requests", "descendant-pipes", "descendant-redirect", "descendant-stubborn"} else "")
        + descendant_setup
        + ("pathlib.Path('../output/actual.json').write_text('external')\n"
           "pathlib.Path('../output/producer-result.json').symlink_to('actual.json')\n"
           if mode == "symlink-envelope" else "")
        + ("import time; time.sleep(2)\n" if mode == "timeout" else ""),
        encoding="utf-8",
    )
    script.chmod(0o755)
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", contract_sha256=DIGEST, evaluator_kind="local",
        evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST, generator_fingerprint=DIGEST,
        dependency_sha256=DIGEST, environment_sha256=DIGEST, producer_id="fixture", producer_fingerprint=DIGEST,
        executable_relative="producer.py", argv=("producer.py",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=2,
        output_max_bytes=1024 if mode in {"overflow", "dual-overflow"} else 65536,
        wall_timeout_seconds=1 if mode == "timeout" else 5,
    )
    return producer_root, intent, build_producer_launch_attestation(intent, "nonce-001")


def test_attested_process_is_registered_before_gate_and_emits_receipt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="gate-order")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "completed"
    assert receipt.gate_released is True
    assert receipt.registration_sha256
    assert receipt.envelope_evidence is not None
    batch = tmp_path / "evolution/producer-batches/journal-001"
    registration = json.loads((batch / "process-registration.json").read_text())
    assert registration["registration_sha256"] == receipt.registration_sha256
    assert (registration["pid"], registration["pgid"]) == (receipt.pid, receipt.pgid)
    assert registration["owner_identity"] == receipt.owner_identity
    assert registration["owner_identity_sha256"] == producer_process._sha(receipt.owner_identity)
    assert receipt.owner_identity["pid"] == receipt.pid
    lock_stat = (batch / ".recovery.lock").stat()
    assert (registration["recovery_lock_device"], registration["recovery_lock_inode"]) == (
        lock_stat.st_dev, lock_stat.st_ino,
    )
    assert (batch / "execution-receipt.json").is_file()


def test_owner_identity_change_denies_cleanup_authority(monkeypatch: pytest.MonkeyPatch):
    owner_identity = {"kind": "test-starttime", "pid": 321, "start": 1}
    process = SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(
        producer_process, "_process_owner_identity",
        lambda _pid: {"kind": "test-starttime", "pid": 321, "start": 2},
    )
    assert producer_process._current_process_owned(321, owner_identity, process) is False


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires OS process identity")
def test_os_process_owner_identity_has_subsecond_or_boot_scoped_start():
    observed = producer_process._process_owner_identity(os.getpid())
    assert observed is not None
    assert observed["pid"] == os.getpid()
    if sys.platform == "darwin":
        assert observed["kind"] == "darwin-libproc-starttime-v1"
        assert observed["start_sec"] > 0
        assert 0 <= observed["start_usec"] < 1_000_000
    else:
        assert observed["kind"] == "linux-proc-starttime-v1"
        assert observed["boot_id"]
        assert observed["starttime_ticks"] > 0


def test_missing_identity_requires_live_controller_child_observation(monkeypatch: pytest.MonkeyPatch):
    owner_identity = {"kind": "test-starttime", "pid": 321, "start": 1}
    monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: None)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: None),
    ) is False
    monkeypatch.setattr(producer_process.os, "getpgid", lambda _pid: 321)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: 0),
    ) is False

    def missing_pid(_pid: int) -> int:
        raise ProcessLookupError()

    monkeypatch.setattr(producer_process.os, "getpgid", missing_pid)
    assert producer_process._current_process_owned(
        321, owner_identity, SimpleNamespace(poll=lambda: 0),
    ) is True


def test_registration_is_durable_before_gate_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    registration_path = tmp_path / "evolution/producer-batches/journal-001/process-registration.json"
    original_write = os.write
    original_fsync = os.fsync
    gate_observations = []
    synced_inodes = set()

    def checked_fsync(fd):
        opened = os.fstat(fd)
        synced_inodes.add((opened.st_dev, opened.st_ino))
        return original_fsync(fd)

    def checked_write(fd, data):
        if data == b"1":
            registration_info = registration_path.stat()
            assert (registration_info.st_dev, registration_info.st_ino) in synced_inodes
            registration = json.loads(registration_path.read_text())
            gate_observations.append(registration)
        return original_write(fd, data)

    monkeypatch.setattr(producer_process.os, "fsync", checked_fsync)
    monkeypatch.setattr(producer_process.os, "write", checked_write)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert len(gate_observations) == 1
    assert gate_observations[0]["registration_sha256"] == receipt.registration_sha256
    assert gate_observations[0]["pid"] == receipt.pid


def test_launch_environment_does_not_inherit_parent_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    monkeypatch.setenv("LUNAR_SECRET", "parent-only")
    monkeypatch.setenv("PATH", str(tmp_path))
    observed = []

    def checked_popen(*args, **kwargs):
        env = kwargs["env"]
        assert env["PATH"] == os.defpath
        assert env["LANG"] == "C"
        assert "LUNAR_SECRET" not in env
        assert set(env) == {"PATH", "LANG", "LUNAR_PRODUCER_GATE_FD"}
        assert kwargs["shell"] is False
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
        assert kwargs["stdin"] is subprocess.DEVNULL
        observed.append(env)
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        popen_factory=checked_popen,
    )
    assert receipt.status == "completed"
    assert len(observed) == 1


def test_process_creation_uses_isolated_no_shell_contract(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    observed: dict[str, object] = {}

    def checked_popen(*args, **kwargs):
        observed["argv"] = args[0]
        observed.update(kwargs)
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path,
        intent=intent,
        attestation=attestation,
        producer_root=producer_root,
        popen_factory=checked_popen,
    )
    assert receipt.status == "completed"
    assert isinstance(observed["argv"], list)
    assert observed["argv"] == list(intent.argv)
    assert observed["shell"] is False
    assert observed["start_new_session"] is True
    assert observed["close_fds"] is True
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["stdout"] is subprocess.PIPE
    assert observed["stderr"] is subprocess.PIPE
    assert observed["cwd"] == str(tmp_path / "evolution/producer-batches/journal-001/work")
    assert len(observed["pass_fds"]) == 1


def test_attestation_nonce_is_consumed_once(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_attestation_replayed"


def test_nonce_cannot_be_reused_by_a_different_launch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    second_intent = replace(intent, launch_id="launch-002", journal_id="journal-002", intent_sha256=None)
    second_attestation = build_producer_launch_attestation(second_intent, attestation.nonce)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("replayed nonce must be rejected before spawning a child")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=second_intent, attestation=second_attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_attestation_replayed"
    assert not (tmp_path / "evolution/producer-batches/journal-002/attestation-consumption.json").exists()
    assert not (tmp_path / "evolution/producer-batches/journal-002/process-registration.json").exists()


@pytest.mark.parametrize("drift", ["bytes", "inode"])
def test_executable_drift_rejected_before_attestation_consumption(tmp_path: Path, drift: str):
    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    if drift == "bytes":
        executable.write_bytes(executable.read_bytes() + b"\n")
    else:
        replacement = producer_root / "replacement.py"
        replacement.write_bytes(executable.read_bytes())
        replacement.chmod(0o755)
        replacement.replace(executable)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("executable drift must be rejected before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_executable_changed"
    assert not (tmp_path / "evolution/producer-batches/journal-001/attestation-consumption.json").exists()


def test_nonzero_exit_is_failed_without_receipt_projection(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="failed")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_exit_failed"


def test_request_count_over_budget_is_failed(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="over-requests")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_request_limit_exceeded"
    assert receipt.request_count == 3


def test_registration_write_failure_never_releases_work_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process._atomic_json

    def fail_registration(path, value, **kwargs):
        if path.name == "process-registration.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(producer_process, "_atomic_json", fail_registration)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_receipt_write_unknown"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert not (batch / "output/producer-result.json").exists()
    assert not (batch / "process-registration.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_registration_missing"


def test_child_exit_before_gate_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path, mode="exit-before-gate")
    original_write = producer_process._atomic_json
    spawned = []

    def tracked_popen(*args, **kwargs):
        process = producer_process.subprocess.Popen(*args, **kwargs)
        spawned.append(process)
        return process

    def exit_after_registration(path, value, **kwargs):
        original_write(path, value, **kwargs)
        if path.name == "process-registration.json":
            (path.parent / "exit-before-gate").touch()
            assert spawned[0].wait(timeout=2) == 7

    monkeypatch.setattr(producer_process, "_atomic_json", exit_after_registration)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=tracked_popen,
        )
    assert exc.value.code == "producer_process_launch_unknown"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "process-registration.json").is_file()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "output/producer-result.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_broken_gate_delivery_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process.os.write
    spawned = []

    def tracked_popen(*args, **kwargs):
        process = producer_process.subprocess.Popen(*args, **kwargs)
        spawned.append(process)
        return process

    def fail_gate_write(fd, data):
        if data == b"1":
            raise BrokenPipeError("gate delivery failed")
        return original_write(fd, data)

    monkeypatch.setattr(producer_process.os, "write", fail_gate_write)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=tracked_popen,
        )
    assert exc.value.code == "producer_process_launch_unknown"
    assert spawned[0].wait(timeout=1) != 0
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "process-registration.json").is_file()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "output/producer-result.json").exists()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_terminal_receipt_write_failure_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    original_write = producer_process._atomic_json

    def fail_terminal(path, value, **kwargs):
        if path.name == "execution-receipt.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(producer_process, "_atomic_json", fail_terminal)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert exc.value.code == "producer_process_receipt_write_unknown"
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def test_output_limit_is_bounded(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="overflow")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_output_limit_exceeded"
    assert receipt.stdout_evidence.bytes_observed > intent.output_max_bytes


def test_simultaneous_stdout_stderr_overflow_does_not_deadlock(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="dual-overflow")
    started = time.monotonic()
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert time.monotonic() - started < intent.wall_timeout_seconds
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_output_limit_exceeded"
    assert receipt.stdout_evidence.bytes_observed > intent.output_max_bytes
    assert receipt.stderr_evidence.bytes_observed > intent.output_max_bytes
    assert receipt.stdout_evidence.truncated is True
    assert receipt.stderr_evidence.truncated is True


def test_hostile_pre_gate_side_effect_is_observable_but_not_trusted_bootstrap(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="hostile-pre-gate")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "completed"
    assert (tmp_path / "evolution/producer-batches/journal-001/pre-gate-side-effect").read_text() == "hostile"
    assert receipt.gate_released is True


def test_capture_digest_keeps_only_in_budget_prefix_when_one_read_crosses_limit():
    read_fd, write_fd = os.pipe()
    payload = b"a" * 100 + b"b" * 100
    os.write(write_fd, payload)
    os.close(write_fd)
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: 0)
            captured, _, overflow, timed_out = producer_process._capture(
                process, limit=100, deadline=time.monotonic() + 1.0,
                monotonic=time.monotonic,
            )
        assert overflow is True
        assert timed_out is False
        assert captured.bytes_observed == 101
        assert captured.truncated is True
        assert captured.sha256 == hashlib.sha256(b"a" * 100).hexdigest()
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
def test_darwin_snapshot_survives_source_replacement_after_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    original = executable.read_bytes()
    observed = {}

    def replacing_popen(*args, **kwargs):
        snapshot = Path(kwargs["executable"])
        flags = os.stat(snapshot, follow_symlinks=False).st_flags
        assert flags & producer_process._UF_IMMUTABLE
        assert snapshot.name == "executable"
        replacement = producer_root / "replacement.py"
        replacement.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib\n"
            "pathlib.Path('../output/producer-result.json').write_text('{}')\n",
            encoding="utf-8",
        )
        replacement.chmod(0o755)
        replacement.replace(executable)
        observed["snapshot"] = snapshot
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path,
        intent=intent,
        attestation=attestation,
        producer_root=producer_root,
        popen_factory=replacing_popen,
    )
    assert receipt.status == "completed"
    assert receipt.execution_binding == "darwin-immutable-snapshot"
    assert receipt.execution_snapshot_sha256 == hashlib.sha256(original).hexdigest()
    assert not observed["snapshot"].exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
def test_darwin_snapshot_roles_keep_bootstrap_and_target_separate(tmp_path: Path):
    batch = tmp_path / "batch"
    batch.mkdir()
    sources = {}
    snapshots = {}
    try:
        for role in ("bootstrap", "target", "producer"):
            source = tmp_path / role
            source.write_bytes(f"#!/bin/sh\n# {role}\n".encode())
            source.chmod(0o755)
            sources[role] = source
            snapshots[role] = producer_process._snapshot_executable(
                source, batch, producer_process._file_identity(source),
                deadline=time.monotonic() + 5, monotonic=time.monotonic, role=role,
            )

        assert {role: snapshot.relative_path for role, snapshot in snapshots.items()} == {
            "bootstrap": ".producer-snapshots/bootstrap",
            "target": ".producer-snapshots/target",
            "producer": ".producer-snapshots/executable",
        }
        for role, snapshot in snapshots.items():
            path = batch / snapshot.relative_path
            assert path.read_bytes() == sources[role].read_bytes()
            assert os.stat(path, follow_symlinks=False).st_flags & producer_process._UF_IMMUTABLE
        for role in ("bootstrap", "target", "producer"):
            producer_process._remove_executable_snapshot(snapshots[role], batch)
            assert not (batch / snapshots[role].relative_path).exists()
    finally:
        for snapshot in snapshots.values():
            producer_process._remove_executable_snapshot(snapshot, batch)


def test_snapshot_rejects_unknown_role_before_platform_binding(tmp_path: Path):
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._snapshot_executable(
            tmp_path / "missing", tmp_path, {},
            deadline=time.monotonic() + 5, monotonic=time.monotonic, role="arbitrary",
        )
    assert exc.value.code == "producer_process_snapshot_role_invalid"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
@pytest.mark.parametrize("role", ("producer", "bootstrap", "target"))
def test_darwin_snapshot_publication_cannot_replace_racing_role_path(tmp_path: Path, monkeypatch, role: str):
    batch = tmp_path / "batch"
    batch.mkdir()
    source = tmp_path / "bootstrap"
    source.write_bytes(b"#!/bin/sh\nexit 0\n")
    source.chmod(0o755)
    real_link = producer_process.os.link
    snapshot_name = "executable" if role == "producer" else role
    snapshot_path = batch / ".producer-snapshots" / snapshot_name

    def occupy_before_publish(src, dst, **kwargs):
        snapshot_path.write_bytes(b"previous attempt")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(producer_process.os, "link", occupy_before_publish)
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._snapshot_executable(
            source, batch, producer_process._file_identity(source),
            deadline=time.monotonic() + 5, monotonic=time.monotonic, role=role,
        )
    assert exc.value.code == "producer_process_execution_binding_unknown"
    assert snapshot_path.read_bytes() == b"previous attempt"
    assert list(snapshot_path.parent.glob(".executable-*")) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin immutable execution snapshots")
def test_darwin_snapshot_lock_failure_rejects_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)

    def fail_chflags(*args, **kwargs):
        raise OSError("immutable flags unavailable")

    monkeypatch.setattr(producer_process.os, "chflags", fail_chflags)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("snapshot lock failure must reject before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path,
            intent=intent,
            attestation=attestation,
            producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_execution_binding_unknown"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux sealed memfd execution")
def test_linux_sealed_executable_survives_source_replacement_after_final_check(tmp_path: Path):
    import fcntl

    producer_root, intent, attestation = _fixture(tmp_path)
    executable = producer_root / "producer.py"
    original_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    observed: dict[str, int] = {}

    def replacing_popen(*args, **kwargs):
        bound_path = kwargs["executable"]
        assert bound_path.startswith("/proc/self/fd/")
        bound_fd = int(bound_path.rsplit("/", 1)[1])
        assert bound_fd in kwargs["pass_fds"]
        required_seals = (
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        )
        assert fcntl.fcntl(bound_fd, fcntl.F_GET_SEALS) & required_seals == required_seals
        observed["fd"] = bound_fd

        replacement = producer_root / "replacement.py"
        replacement.write_text("#!/usr/bin/env python3\nraise SystemExit(9)\n", encoding="utf-8")
        replacement.chmod(0o755)
        replacement.replace(executable)
        return producer_process.subprocess.Popen(*args, **kwargs)

    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        popen_factory=replacing_popen,
    )
    assert receipt.status == "completed"
    assert receipt.execution_binding == "linux-sealed-memfd"
    assert receipt.execution_snapshot_sha256 == original_digest
    assert receipt.execution_snapshot_relative_path is None
    registration = json.loads(
        (tmp_path / "evolution/producer-batches/journal-001/process-registration.json").read_text()
    )
    assert registration["execution_binding"] == "linux-sealed-memfd"
    assert registration["execution_snapshot_sha256"] == original_digest
    with pytest.raises(OSError):
        os.fstat(observed["fd"])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux runner path")
def test_linux_binding_unavailable_rejects_before_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)

    @contextmanager
    def unavailable(*args, **kwargs):
        raise LinuxExecutableBindingError("linux_execution_binding_unsupported")
        yield

    monkeypatch.setattr(producer_process, "sealed_linux_executable", unavailable)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("an unsupported execution binding must reject before spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_execution_binding_unsupported"
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert (batch / "attestation-consumption.json").is_file()
    assert not (batch / "process-registration.json").exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
@pytest.mark.parametrize("mode", ["descendant-pipes", "descendant-redirect", "descendant-stubborn"])
def test_leader_exit_cleans_remaining_descendant_group(tmp_path: Path, mode: str):
    producer_root, intent, attestation = _fixture(tmp_path, mode=mode)
    started = time.monotonic()
    receipt = None
    try:
        receipt = run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        )
        assert time.monotonic() - started < intent.wall_timeout_seconds
        assert receipt.status == "completed"
        assert receipt.cleanup_status in {"cleaned", "already_exited"}
        if mode == "descendant-stubborn":
            assert receipt.cleanup_status == "cleaned"
        with pytest.raises(ProcessLookupError):
            os.killpg(receipt.pgid, 0)
    finally:
        if receipt is not None:
            try:
                os.killpg(receipt.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_capture_timeout_does_not_read_open_pipe_after_deadline():
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: 0)
            _, _, overflow, timed_out = producer_process._capture(
                process, limit=1024, deadline=0.0, monotonic=lambda: 1.0,
            )
        assert overflow is False
        assert timed_out is True
    finally:
        os.close(write_fd)


def test_remaining_timeout_never_extends_absolute_deadline():
    assert producer_process._remaining_timeout(10.0, lambda: 9.25) == pytest.approx(0.75)
    assert producer_process._remaining_timeout(10.0, lambda: 10.0) == 0.0
    assert producer_process._remaining_timeout(10.0, lambda: 10.25) == 0.0


def test_capture_read_failure_is_unknown(monkeypatch: pytest.MonkeyPatch):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"x")
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            process = SimpleNamespace(stdout=stdout, stderr=None, poll=lambda: None)
            original_read = producer_process.os.read

            def fail_read(fd: int, size: int) -> bytes:
                if fd == read_fd:
                    raise OSError("capture read unavailable")
                return original_read(fd, size)

            monkeypatch.setattr(producer_process.os, "read", fail_read)
            with pytest.raises(ProducerProcessError) as exc:
                producer_process._capture(
                    process, limit=1024, deadline=time.monotonic() + 1.0,
                    monotonic=time.monotonic,
                )
        assert exc.value.code == "producer_process_capture_unknown"
    finally:
        os.close(write_fd)


def test_cleanup_signal_uncertainty_is_persisted_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    producer_root, intent, attestation = _fixture(tmp_path)

    def uncertain_cleanup(registration, **kwargs):
        return ProcessCleanupResult(
            label=registration.label,
            pid=registration.pid,
            pgid=registration.pgid,
            status=ProcessCleanupStatus.KILL_FAILED,
            alive_after=True,
        )

    monkeypatch.setattr(producer_process, "cleanup_registered_process", uncertain_cleanup)
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
    )
    assert receipt.status == "unknown"
    assert receipt.failure_code == "producer_process_cleanup_unknown"


def test_cleanup_passes_absolute_deadline_and_rechecks_exited_leader(
    monkeypatch: pytest.MonkeyPatch,
):
    registration = producer_process.RegisteredProcess(321, 654, owner_check=lambda: True)
    observed: dict[str, object] = {}

    def checked_cleanup(registration, **kwargs):
        observed.update(kwargs)
        return ProcessCleanupResult(
            label=registration.label,
            pid=registration.pid,
            pgid=registration.pgid,
            status=ProcessCleanupStatus.ALREADY_EXITED,
        )

    monkeypatch.setattr(producer_process, "cleanup_registered_process", checked_cleanup)
    process = SimpleNamespace(returncode=None, poll=lambda: 7)
    producer_process._cleanup(registration, process, deadline=10.0, monotonic=lambda: 9.0)

    assert observed["deadline"] == 10.0
    assert observed["allow_exited_leader_initial"] is True


def test_preparation_time_counts_toward_wall_deadline(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    times = iter((0.0, 6.0))

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("expired launch must not spawn")

    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            monotonic=lambda: next(times), popen_factory=forbidden_spawn,
        )
    assert exc.value.code == "producer_process_wall_timeout"
    assert recover_producer_process(tmp_path, journal_id=intent.journal_id)["status"] == "recovery_required"


def test_envelope_read_obeys_wall_deadline(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "producer-result.json").write_text("{}", encoding="utf-8")
    times = iter((0.0, 2.0))
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._read_envelope(
            output / "producer-result.json", relative_path="output/producer-result.json",
            limit=1024, deadline=1.0, monotonic=lambda: next(times),
        )
    assert exc.value.code == "producer_process_wall_timeout"


def test_envelope_rejects_duplicate_json_keys(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "producer-result.json").write_text('{"budget":{"requests":1,"requests":1}}', encoding="utf-8")
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._read_envelope(
            output / "producer-result.json", relative_path="output/producer-result.json",
            limit=1024, deadline=1.0, monotonic=lambda: 0.0,
        )
    assert exc.value.code == "producer_process_envelope_invalid"


def test_timeout_is_terminal_without_relaunch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="timeout")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status in {"failed", "unknown"}
    assert receipt.failure_code in {"producer_process_wall_timeout", "producer_process_cleanup_unknown"}


def test_active_cancellation_terminates_child_and_persists_cancelled_receipt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="timeout")
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        # The first three observations happen before/around registration; the next one is
        # reached by the nonblocking capture loop while the sleeping child is still running.
        return calls >= 5

    started = time.monotonic()
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        cancelled=cancelled,
    )
    assert receipt.status == "cancelled"
    assert receipt.failure_code is None
    assert receipt.cleanup_status in {"cleaned", "already_exited"}
    assert calls >= 5
    assert time.monotonic() - started < intent.wall_timeout_seconds
    assert recover_producer_process(tmp_path, journal_id=intent.journal_id) == receipt.to_dict()


def test_active_cancellation_cleanup_uncertainty_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path, mode="timeout")
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 5

    def uncertain_cleanup(registration, **kwargs):
        return ProcessCleanupResult(
            label=registration.label,
            pid=registration.pid,
            pgid=registration.pgid,
            status=ProcessCleanupStatus.KILL_FAILED,
            alive_after=True,
        )

    monkeypatch.setattr(producer_process, "cleanup_registered_process", uncertain_cleanup)
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        cancelled=cancelled,
    )
    assert receipt.status == "unknown"
    assert receipt.failure_code == "producer_process_cleanup_unknown"


def test_parent_deadline_narrows_intent_wall_budget(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="timeout")
    started = time.monotonic()
    receipt = run_producer_process(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        parent_deadline=started + 0.2,
    )
    assert receipt.status == "unknown"
    assert receipt.failure_code in {"producer_process_wall_timeout", "producer_process_cleanup_unknown"}
    assert time.monotonic() - started < intent.wall_timeout_seconds


def test_invalid_parent_deadline_fails_before_attestation_consumption(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    with pytest.raises(ProducerProcessError, match="parent_deadline_invalid"):
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            parent_deadline=float("nan"), popen_factory=lambda *args, **kwargs: pytest.fail("must not spawn"),
        )
    assert not (tmp_path / "evolution/producer-batches/journal-001/attestation-consumption.json").exists()


@pytest.mark.parametrize(
    ("callback", "code"),
    [
        (lambda: 1, "producer_process_cancellation_invalid"),
        (lambda: (_ for _ in ()).throw(RuntimeError("callback failed")), "producer_process_cancellation_unknown"),
    ],
)
def test_cancellation_callback_failure_is_fail_closed_before_spawn(
    tmp_path: Path, callback, code: str,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    with pytest.raises(ProducerProcessError) as exc:
        run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            cancelled=callback, popen_factory=lambda *args, **kwargs: pytest.fail("must not spawn"),
        )
    assert exc.value.code == code


def test_symlink_envelope_is_rejected_with_terminal_receipt(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path, mode="symlink-envelope")
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_envelope_invalid"
    assert receipt.envelope_evidence is None
    assert (tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json").is_file()


def test_replaced_envelope_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    output = tmp_path / "evolution/producer-batches/journal-001/output"
    output.mkdir(parents=True)
    envelope = output / "producer-result.json"
    replacement = output / "replacement.json"
    replacement.write_text("replacement", encoding="utf-8")
    original_open = os.open
    replaced = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == envelope.name and kwargs.get("dir_fd") is not None and not replaced:
            replacement.replace(envelope)
            replaced = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(producer_process.os, "open", swapping_open)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert replaced
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_envelope_changed"
    assert receipt.envelope_evidence is None


@pytest.mark.parametrize("mutation", ["truncate", "append"])
def test_envelope_mutation_after_open_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str):
    output = tmp_path / "output"
    output.mkdir()
    envelope = output / "producer-result.json"
    payload = b'{"budget":{"requests":1}}'
    envelope.write_bytes(payload)
    original_open = os.open
    original_read = os.read
    target_fd: int | None = None
    mutated = False

    def tracking_open(path, flags, *args, **kwargs):
        nonlocal target_fd
        fd = original_open(path, flags, *args, **kwargs)
        if path == envelope.name and kwargs.get("dir_fd") is not None:
            target_fd = fd
        return fd

    def mutate_after_first_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        data = original_read(fd, size)
        if fd == target_fd and data and not mutated:
            mutated = True
            if mutation == "truncate":
                envelope.write_bytes(b"")
            else:
                envelope.write_bytes(payload + b" ")
        return data

    monkeypatch.setattr(producer_process.os, "open", tracking_open)
    monkeypatch.setattr(producer_process.os, "read", mutate_after_first_read)
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._read_envelope(
            envelope,
            relative_path="output/producer-result.json",
            limit=1024,
            deadline=time.monotonic() + 1.0,
            monotonic=time.monotonic,
        )
    assert mutated is True
    assert exc.value.code == "producer_process_envelope_changed"


def test_atomic_receipt_fsync_failure_does_not_publish_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "batch" / "execution-receipt.json"

    def fail_fsync(_fd: int) -> None:
        raise OSError("receipt fsync failed")

    monkeypatch.setattr(producer_process.os, "fsync", fail_fsync)
    with pytest.raises(ProducerProcessError) as exc:
        producer_process._atomic_json(target, {"schema_version": "1"})
    assert exc.value.code == "producer_process_receipt_write_unknown"
    assert not target.exists()
    assert not list(target.parent.glob(".producer-receipt-*"))


def test_replaced_output_directory_during_read_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    batch = tmp_path / "evolution/producer-batches/journal-001"
    output = batch / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "producer-result.json").write_text("{}", encoding="utf-8")
    original_open = os.open
    replaced = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "producer-result.json" and kwargs.get("dir_fd") is not None and not replaced:
            output.replace(batch / "moved-output")
            output.symlink_to(outside, target_is_directory=True)
            replaced = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(producer_process.os, "open", swapping_open)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    assert replaced
    assert receipt.status == "failed"
    assert receipt.failure_code == "producer_process_directory_invalid"
    assert receipt.envelope_evidence is None


def test_recovery_reads_terminal_receipt_without_relaunch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    producer_root, intent, attestation = _fixture(tmp_path)
    receipt = run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)

    def forbidden_spawn(*args, **kwargs):
        pytest.fail("recovery must not relaunch the producer")

    monkeypatch.setattr(producer_process.subprocess, "Popen", forbidden_spawn)
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["receipt_sha256"] == receipt.receipt_sha256
    assert recovered["registration_sha256"] == receipt.registration_sha256


def test_missing_terminal_receipt_requires_recovery_without_relaunch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    (tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json").unlink()
    recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "producer_process_terminal_receipt_missing"


def _registered_live_process(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    batch = tmp_path / "evolution/producer-batches/journal-001"
    (batch / "execution-receipt.json").unlink()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    registration_path = batch / "process-registration.json"
    registration = json.loads(registration_path.read_text())
    registration["pid"] = process.pid
    registration["pgid"] = os.getpgid(process.pid)
    registration["owner_identity"] = producer_process._process_owner_identity(process.pid)
    assert registration["owner_identity"] is not None
    registration["owner_identity_sha256"] = producer_process._sha(registration["owner_identity"])
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    registration_path.write_bytes(producer_process._canonical(registration))
    return batch, intent, process


def test_explicit_recovery_cleans_only_registered_owner_and_writes_receipt(tmp_path: Path):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        observed = recover_producer_process(tmp_path, journal_id=intent.journal_id)
        assert observed["status"] == "recovery_required"
        assert not (batch / "recovery-receipt.json").exists()
        recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert recovered["status"] == "recovery_required"
        assert recovered["term_sent"] is True
        assert recovered["cleanup_status"] in {"cleaned", "cleanup_unverified", "ownership_lost"}
        assert recovered["recovery_sha256"] == producer_process._digest_without(recovered, "recovery_sha256")
        assert recover_producer_process(tmp_path, journal_id=intent.journal_id) == recovered
        with pytest.raises(ProducerProcessError) as exc:
            recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert exc.value.code == "producer_process_recovery_already_recorded"
        assert not (batch / "execution-receipt.json").exists()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_denies_changed_owner_without_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: None)
        recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert recovered["cleanup_status"] == "ownership_lost"
        assert recovered["term_sent"] is False
        assert process.poll() is None
        assert (batch / "recovery-receipt.json").is_file()
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_rejects_busy_lifecycle_lock(tmp_path: Path):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        with producer_process._recovery_lock(batch), pytest.raises(ProducerProcessError) as exc:
            recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert exc.value.code == "producer_process_recovery_busy"
        assert process.poll() is None
        assert not (batch / "recovery-receipt.json").exists()
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_rejects_replaced_lock_while_controller_holds_old_inode(tmp_path: Path):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        with producer_process._recovery_lock(batch):
            (batch / ".recovery.lock").rename(batch / ".recovery.lock.old")
            with pytest.raises(ProducerProcessError) as exc:
                recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
            assert exc.value.code == "producer_process_recovery_registration_invalid"
            assert process.poll() is None
            assert not (batch / "recovery-receipt.json").exists()
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_loses_authority_if_lock_changes_before_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    batch, intent, process = _registered_live_process(tmp_path)
    original_cleanup = producer_process.cleanup_registered_process

    def replace_lock_before_cleanup(*args, **kwargs):
        (batch / ".recovery.lock").rename(batch / ".recovery.lock.old")
        (batch / ".recovery.lock").touch()
        return original_cleanup(*args, **kwargs)

    monkeypatch.setattr(producer_process, "cleanup_registered_process", replace_lock_before_cleanup)
    try:
        recovered = recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert recovered["cleanup_status"] == "ownership_lost"
        assert recovered["term_sent"] is False
        assert process.poll() is None
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_rejects_tampered_recovery_receipt(tmp_path: Path):
    batch, intent, process = _registered_live_process(tmp_path)
    try:
        recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        path = batch / "recovery-receipt.json"
        receipt = json.loads(path.read_text())
        receipt["status"] = "completed"
        path.write_bytes(producer_process._canonical(receipt))
        with pytest.raises(ProducerProcessError) as exc:
            recover_producer_process(tmp_path, journal_id=intent.journal_id, cleanup=True)
        assert exc.value.code == "producer_process_recovery_receipt_invalid"
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_recovery_rejects_registration_owner_identity_mismatch(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    batch = tmp_path / "evolution/producer-batches/journal-001"
    (batch / "execution-receipt.json").unlink()
    path = batch / "process-registration.json"
    registration = json.loads(path.read_text())
    registration["owner_identity"]["pid"] += 1
    registration["owner_identity_sha256"] = producer_process._sha(registration["owner_identity"])
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    path.write_bytes(producer_process._canonical(registration))
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_registration_invalid"


def _recovery_registration(tmp_path: Path, pid: int, pgid: int, owner: dict[str, object]) -> Path:
    batch = tmp_path / "evolution/producer-batches/journal-001"
    batch.mkdir(parents=True)
    with producer_process._recovery_lock(batch) as lock_identity:
        pass
    claim = {
        "schema_version": "1", "protocol": producer_process.PRODUCER_PROCESS_PROTOCOL,
        "consumption_id": "launch-001", "launch_id": "launch-001", "journal_id": "journal-001",
        "run_id": "run-001", "parent_task_id": "parent-001", "task_id": "task-001",
        "intent_sha256": DIGEST, "attestation_sha256": DIGEST,
        "nonce": "nonce-001", "executable_identity": DIGEST,
    }
    claim["consumption_sha256"] = producer_process._digest_without(claim, "consumption_sha256")
    registration = {
        "schema_version": "1", "protocol": producer_process.PRODUCER_PROCESS_PROTOCOL,
        **{key: claim[key] for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256", "consumption_sha256", "executable_identity",
        )},
        "pid": pid, "pgid": pgid, "owner_identity": owner,
        "owner_identity_sha256": producer_process._sha(owner),
        "recovery_lock_protocol": producer_process._RECOVERY_LOCK_PROTOCOL,
        "recovery_lock_device": lock_identity[0], "recovery_lock_inode": lock_identity[1],
    }
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    producer_process._atomic_json(batch / "attestation-consumption.json", claim, exclusive=True)
    nonce_key = hashlib.sha256(b"nonce-001").hexdigest()
    producer_process._atomic_json(
        tmp_path / "evolution/producer-nonces" / f"{nonce_key}.json", claim, exclusive=True,
    )
    producer_process._atomic_json(batch / "process-registration.json", registration, exclusive=True)
    return batch


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires OS process identity")
def test_explicit_recovery_cleans_exact_live_owner_and_records_unknown(tmp_path: Path):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        owner = producer_process._process_owner_identity(process.pid)
        assert owner is not None
        batch = _recovery_registration(tmp_path, process.pid, process.pid, owner)
        receipt = recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
        assert receipt["status"] == "recovery_required"
        assert receipt["execution_outcome"] == "unknown"
        assert receipt["cleanup_status"] in {"cleaned", "cleanup_unverified", "ownership_lost"}
        assert receipt["term_sent"] is True
        assert receipt["registration_sha256"] == json.loads(
            (batch / "process-registration.json").read_text()
        )["registration_sha256"]
        assert recover_producer_process(tmp_path, journal_id="journal-001") == receipt
        with pytest.raises(ProducerProcessError) as exc:
            recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
        assert exc.value.code == "producer_process_recovery_already_recorded"
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="requires OS process identity")
def test_explicit_recovery_owner_mismatch_never_signals(tmp_path: Path):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        owner = producer_process._process_owner_identity(process.pid)
        assert owner is not None
        owner["kind"] = "different-start-identity"
        _recovery_registration(tmp_path, process.pid, process.pid, owner)
        receipt = recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
        assert receipt["cleanup_status"] == "ownership_lost"
        assert receipt["term_sent"] is False
        assert process.poll() is None
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def test_explicit_recovery_absent_group_records_no_signal(tmp_path: Path):
    pid = os.getpid() + 10_000_000
    _recovery_registration(tmp_path, pid, pid, {"kind": "absent", "pid": pid})
    receipt = recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
    assert receipt["cleanup_status"] == "already_exited"
    assert receipt["term_sent"] is False


def test_explicit_recovery_rejects_legacy_registration_without_lifecycle_lock(tmp_path: Path):
    pid = os.getpid() + 10_000_000
    batch = _recovery_registration(tmp_path, pid, pid, {"kind": "absent", "pid": pid})
    path = batch / "process-registration.json"
    registration = json.loads(path.read_text())
    del registration["recovery_lock_protocol"]
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    path.write_bytes(producer_process._canonical(registration))
    assert recover_producer_process(tmp_path, journal_id="journal-001")["status"] == "recovery_required"
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
    assert exc.value.code == "producer_process_recovery_registration_invalid"
    assert not (batch / "recovery-receipt.json").exists()


@pytest.mark.parametrize("field", ["recovery_lock_device", "recovery_lock_inode"])
def test_explicit_recovery_rejects_legacy_registration_without_lock_identity(
    tmp_path: Path, field: str,
):
    pid = os.getpid() + 10_000_000
    batch = _recovery_registration(tmp_path, pid, pid, {"kind": "absent", "pid": pid})
    path = batch / "process-registration.json"
    registration = json.loads(path.read_text())
    del registration[field]
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    path.write_bytes(producer_process._canonical(registration))
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
    assert exc.value.code == "producer_process_recovery_registration_invalid"
    assert not (batch / "recovery-receipt.json").exists()


def test_explicit_recovery_receipt_write_failure_keeps_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pid = os.getpid() + 10_000_000
    batch = _recovery_registration(tmp_path, pid, pid, {"kind": "absent", "pid": pid})
    original_write = producer_process._atomic_json

    def fail_recovery_receipt(path, value, **kwargs):
        if path.name == "recovery-receipt.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(producer_process, "_atomic_json", fail_recovery_receipt)
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
    assert exc.value.code == "producer_process_recovery_receipt_write_unknown"
    assert not (batch / "recovery-receipt.json").exists()
    observed = recover_producer_process(tmp_path, journal_id="journal-001")
    assert observed["status"] == "recovery_required"
    assert observed["reason"] == "producer_process_terminal_receipt_missing"


@pytest.mark.parametrize("field", ["pgid", "run_id", "recovery_lock_protocol"])
def test_explicit_recovery_rejects_malformed_registration_tuple(tmp_path: Path, field: str):
    pid = os.getpid() + 10_000_000
    batch = _recovery_registration(tmp_path, pid, pid, {"kind": "absent", "pid": pid})
    path = batch / "process-registration.json"
    registration = json.loads(path.read_text())
    registration[field] = 0 if field == "pgid" else "tampered"
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    path.write_bytes(producer_process._canonical(registration))
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001", cleanup=True)
    assert exc.value.code == "producer_process_recovery_registration_invalid"
    assert not (batch / "recovery-receipt.json").exists()


def test_recovery_rejects_symlinked_receipt(tmp_path: Path):
    batch = tmp_path / "evolution/producer-batches/journal-001"
    batch.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (batch / "execution-receipt.json").symlink_to(outside)
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id="journal-001")
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_tampered_receipt_digest(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    path = tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json"
    altered = json.loads(path.read_text())
    altered["run_id"] = "different-run"
    path.write_text(json.dumps(altered), encoding="utf-8")

    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_duplicate_receipt_keys(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    path = tmp_path / "evolution/producer-batches/journal-001/execution-receipt.json"
    path.write_text(path.read_text()[:-1] + ',"status":"completed"}', encoding="utf-8")
    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"


def test_recovery_rejects_symlinked_batch_directory(tmp_path: Path):
    producer_root, intent, attestation = _fixture(tmp_path)
    run_producer_process(tmp_path, intent=intent, attestation=attestation, producer_root=producer_root)
    batches = tmp_path / "evolution/producer-batches"
    actual = batches / "journal-001"
    moved = batches / "moved"
    actual.replace(moved)
    actual.symlink_to(moved, target_is_directory=True)

    with pytest.raises(ProducerProcessError) as exc:
        recover_producer_process(tmp_path, journal_id=intent.journal_id)
    assert exc.value.code == "producer_process_recovery_receipt_invalid"
