"""Real independent native receiver fixtures; no account/production acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_independent_guardian import _TREE, _inactive, _read, _ReadyWatcher

import lunar_evolution.native_guardian_custody as custody
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.linux_executable_binding import sealed_linux_executable
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_guardian import NativeGuardianError
from lunar_evolution.native_guardian_custody import (
    GuardianCustodyReference,
    inspect_native_guardian_custody,
    native_guardian_receiver_source_path,
    start_durable_native_guardian,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux native custody receiver")

_CONTEXT = "a" * 64
_LAUNCH = "b" * 64
_PROFILE = "c" * 64


def test_custody_start_observes_exact_receiver_and_preserves_failed_owner(monkeypatch):
    process, watcher = _ReadyWatcher(pid=101), _ReadyWatcher(pid=102)
    receiver = SimpleNamespace(fd=8, executable="/proc/self/fd/8", sha256="d" * 64)
    bootstrap = SimpleNamespace(fd=9, sha256="e" * 64)
    chain = SimpleNamespace(fd=10)
    calls, closed = [], []

    def clock():
        return .25

    def wait(fd, deadline, monotonic, *, watcher):
        calls.append((fd, deadline, monotonic, watcher))
        raise NativeGuardianError("native_guardian_ready_invalid")

    def info(fd):
        return SimpleNamespace(st_dev=38, st_ino={3: 31, 4: 41, 5: 51, 6: 51}[fd])

    monkeypatch.setattr(custody.sys, "platform", "linux")
    monkeypatch.setattr(custody, "_POPEN", _ReadyWatcher)
    monkeypatch.setattr(custody.subprocess, "Popen", lambda *_args, **_kwargs: watcher)
    monkeypatch.setattr(custody.os, "pidfd_open", lambda *_args: 7, raising=False)
    monkeypatch.setattr(custody.os, "getpgid", lambda _pid: process.pid)
    monkeypatch.setattr(custody.os, "getsid", lambda _pid: process.pid)
    monkeypatch.setattr(custody.os, "fstat", info)
    monkeypatch.setattr(custody.os, "close", closed.append)
    monkeypatch.setattr(custody, "_elf", lambda _binding: None)
    monkeypatch.setattr(custody, "_pipe", lambda *_args: None)
    monkeypatch.setattr(custody, "_private_chain", lambda _chain: [[38, 10, 0o40700, 2110, 2100]])
    monkeypatch.setattr(custody, "_wait_ready", wait)
    monkeypatch.setattr(custody, "inspect_native_guardian_custody",
                        lambda *_args, **_kwargs: pytest.fail("failed readiness reached registration read"))
    with pytest.raises(NativeGuardianError, match="native_guardian_custody_start_invalid") as caught:
        start_durable_native_guardian(
            process=process, receiver=receiver, bootstrap=bootstrap,
            lifeline_fd=3, finish_fd=4, ack_fd=5, ack_read_fd=6,
            original_directory_chain=chain, original_context_sha256=_CONTEXT,
            original_launch_sha256=_LAUNCH, original_profile_sha256=_PROFILE,
            deadline=1.0, deadline_ns=1_000_000_000, monotonic=clock,
        )
    assert calls == [(6, 1.0, clock, watcher)]
    assert caught.value.guardian_owner._watcher is watcher
    assert caught.value.guardian_owner._bootstrap is process
    assert caught.value.guardian_owner._group_fd == 7
    assert closed == []


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-guardian-custody")
    receiver = root / "receiver"
    compile_native_target(native_guardian_receiver_source_path(), receiver)
    tree_source, tree = root / "tree.c", root / "tree"
    tree_source.write_text(_TREE)
    compile_native_target(tree_source, tree)
    return SimpleNamespace(receiver=receiver, tree=tree,
                           guardian=build_native_bootstrap_artifact(root / "guardian").path)


def _identity(path):
    info = path.stat()
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": info.st_size,
            "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _authority_false(report):
    for name in ("native_success", "publication_authority", "cleanup_authority", "production_admission",
                 "isolation_accepted", "immutable_custody_verified", "whole_group_cleanup_verified",
                 "signal_result_known"):
        assert report[name] is False
    assert report["cleanup_status"] == "unknown"


@contextmanager
def _attempt(binaries, tmp_path, *, budget=4.0, preexisting=False,
             observation_deadline_ns=None):
    directory = tmp_path / "custody"
    directory.mkdir(mode=0o700)
    if preexisting:
        (directory / "guardian-registration-v1.json").write_bytes(b"original-conflict")
    deadline = time.monotonic() + budget
    native_deadline = time.monotonic_ns() + int((deadline - time.monotonic()) * 1e9)
    process = subprocess.Popen([str(binaries.tree), str(tmp_path), "0"], start_new_session=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    owner = None
    fds = set()

    def pipe():
        result = os.pipe()
        fds.update(result)
        return result

    def close(fd):
        if fd in fds:
            fds.remove(fd)
            os.close(fd)

    try:
        with ExitStack() as stack:
            chain = DirectoryChain(directory, "fixture_directory_drift")
            stack.callback(chain.close)
            receiver = stack.enter_context(sealed_linux_executable(
                binaries.receiver, _identity(binaries.receiver), deadline=deadline,
            ))
            guardian = stack.enter_context(sealed_linux_executable(
                binaries.guardian, _identity(binaries.guardian), deadline=deadline,
            ))
            life_r, life_w = pipe()
            finish_r, finish_w = pipe()
            ack_r, ack_w = pipe()
            try:
                owner = start_durable_native_guardian(
                    process=process, receiver=receiver, bootstrap=guardian,
                    lifeline_fd=life_r, finish_fd=finish_r, ack_fd=ack_w, ack_read_fd=ack_r,
                    original_directory_chain=chain, original_context_sha256=_CONTEXT,
                    original_launch_sha256=_LAUNCH, original_profile_sha256=_PROFILE,
                    deadline=deadline, deadline_ns=native_deadline,
                )
            except NativeGuardianError as error:
                owner = error.guardian_owner
                raise
            for fd in (life_r, finish_r, ack_w):
                close(fd)
            yield SimpleNamespace(owner=owner, process=process, chain=chain, directory=directory,
                                  life=life_w, finish=finish_w, ack=ack_r, close=close,
                                  native_deadline=native_deadline)
    finally:
        for fd in tuple(fds):
            close(fd)
        cleanup_remaining = (0.5 if observation_deadline_ns is None else
                             max(0, (observation_deadline_ns - time.monotonic_ns()) / 1e9))
        if owner is not None and cleanup_remaining > 0:
            owner.cleanup(timeout=min(0.5, cleanup_remaining))
        if process.poll() is None:
            process.kill()  # original exact Popen, never a stored PID/PGID
        process.wait(timeout=3 if observation_deadline_ns is None else
                     max(0, (observation_deadline_ns - time.monotonic_ns()) / 1e9))


def test_native_receiver_durable_registration_and_exact_d_exit_then_readonly_drift(binaries, tmp_path):
    with _attempt(binaries, tmp_path) as value:
        original = value.owner.reference
        registered = inspect_native_guardian_custody(original, original_directory_chain=value.chain)
        assert registered["state"] == "registered"
        _authority_false(registered)
        assert (value.directory / "guardian-event-v1.json").stat().st_size == 0
        os.write(value.finish, b"F")
        value.close(value.finish)
        assert _read(value.ack) == b"D"  # receiver committed event before this ACK
        assert value.owner._watcher.wait(timeout=3) == 0
        value.process.kill()
        value.process.wait(timeout=3)
        value.owner.finish()
        report = inspect_native_guardian_custody(original, original_directory_chain=value.chain)
        assert report["state"] == "watcher_exit_observed"
        assert report["native_d_observed"] is True
        assert (report["watcher_exit_kind"], report["watcher_exit_value"]) == (1, 0)
        _authority_false(report)
        # Partial writes, changed originals and an inode substitution never get
        # repaired or promoted into original native completion/cleanup evidence.
        event = value.directory / "guardian-event-v1.json"
        event_bytes = event.read_bytes()
        event.write_bytes(event_bytes[:17])
        assert inspect_native_guardian_custody(original, original_directory_chain=value.chain)["state"] == "unavailable"
        assert event.read_bytes() == event_bytes[:17]
        event.write_bytes(event_bytes)
        changed = json.loads(original.canonical_bytes)
        changed["context_sha256"] = "d" * 64
        drifted = GuardianCustodyReference(json.dumps(changed, sort_keys=True, separators=(",", ":")).encode())
        assert inspect_native_guardian_custody(drifted, original_directory_chain=value.chain)["state"] == "unavailable"
        event.rename(value.directory / "retained-event")
        event.write_bytes(event_bytes)
        event.chmod(0o600)
        assert inspect_native_guardian_custody(original, original_directory_chain=value.chain)["state"] == "unavailable"


def test_existing_custody_refuses_before_readiness_without_replacing_original(binaries, tmp_path):
    with pytest.raises(NativeGuardianError) as failure, _attempt(binaries, tmp_path, preexisting=True):
        pytest.fail("duplicate custody must not release the original gate")
    assert failure.value.guardian_owner is not None
    assert (tmp_path / "custody" / "guardian-registration-v1.json").read_bytes() == b"original-conflict"
    assert not (tmp_path / "custody" / "guardian-event-v1.json").exists()


def test_original_deadline_does_not_allocate_a_post_expiry_event_budget(binaries, tmp_path):
    with _attempt(binaries, tmp_path, budget=0.8) as value:
        assert value.owner._watcher.wait(timeout=3) == 78
        assert value.process.wait(timeout=3) < 0
        assert (value.directory / "guardian-event-v1.json").read_bytes() == b""
        report = inspect_native_guardian_custody(value.owner.reference,
                                               original_directory_chain=value.chain)
        assert report["state"] == "registered"
        assert report["deadline_monotonic_ns"] == value.native_deadline
        _authority_false(report)
        # Killing/reaping only a receiver is not proof of nested guardian reap.
        assert value.owner.cleanup(timeout=0.1) is False


def test_stalled_original_receiver_cannot_delay_guardian_execution_deadline(binaries, tmp_path):
    # One outer observation/reap bound is fixed before launch. It never changes
    # the receiver/guardian's original 0.8-second execution deadline or permits
    # a new event publication after expiry. This does not block an fsync syscall.
    observation_deadline_ns = time.monotonic_ns() + 20_000_000_000

    def observation_remaining():
        remaining = (observation_deadline_ns - time.monotonic_ns()) / 1e9
        assert remaining > 0, "original fixture observation budget expired; retirement unknown"
        return remaining

    with _attempt(binaries, tmp_path, budget=0.8,
                  observation_deadline_ns=observation_deadline_ns) as value:
        receiver = value.owner._watcher
        original = value.owner.reference
        registration = value.directory / "guardian-registration-v1.json"
        event = value.directory / "guardian-event-v1.json"
        registration_pin = _identity(registration)
        cleanup = None
        try:
            receiver.send_signal(signal.SIGSTOP)  # exact original Popen, never a saved PID
            while True:
                assert time.monotonic_ns() < value.native_deadline
                assert receiver.poll() is None
                stopped = os.waitid(os.P_PID, receiver.pid, os.WSTOPPED | os.WNOHANG | os.WNOWAIT)
                if stopped is not None:
                    assert (stopped.si_pid, stopped.si_code, stopped.si_status) == (
                        receiver.pid, os.CLD_STOPPED, signal.SIGSTOP)
                    break
                time.sleep(min(0.01, observation_remaining()))
            # The controller's lifeline writer remains live. Only the original
            # guardian deadline, not parent EOF or receiver cleanup, stops work.
            assert value.process.wait(timeout=observation_remaining()) == -signal.SIGKILL
            assert time.monotonic_ns() >= value.native_deadline
            assert receiver.poll() is None
            assert event.read_bytes() == b""
            assert _identity(registration) == registration_pin
            report = inspect_native_guardian_custody(original, original_directory_chain=value.chain)
            assert report["state"] == "registered"
            assert report["deadline_monotonic_ns"] == value.native_deadline
            _authority_false(report)
        finally:
            # Always resume first, even if stop observation/assertions failed.
            # Native owner cleanup retains its expired execution bound; this
            # outer budget only settles these exact already-owned children.
            try:
                receiver.send_signal(signal.SIGCONT)
            finally:
                try:
                    cleanup = value.owner.cleanup(timeout=observation_remaining())
                finally:
                    receiver.wait(timeout=observation_remaining())
        assert cleanup is False
        assert _identity(registration) == registration_pin and event.read_bytes() == b""
        report = inspect_native_guardian_custody(original, original_directory_chain=value.chain)
        assert report["state"] == "registered"
        assert report["deadline_monotonic_ns"] == value.native_deadline
        _authority_false(report)


_CONTROLLER = r'''
import hashlib,json,os,subprocess,sys,time
from contextlib import ExitStack
from pathlib import Path
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.linux_executable_binding import sealed_linux_executable
from lunar_evolution.native_guardian_custody import start_durable_native_guardian
def identity(path):
    info=path.stat()
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=info.st_size,
                device=info.st_dev,inode=info.st_ino,mtime_ns=info.st_mtime_ns,ctime_ns=info.st_ctime_ns)
receiver,guardian,tree,root=map(Path,sys.argv[1:])
deadline=time.monotonic()+5
native_deadline=time.monotonic_ns()+int((deadline-time.monotonic())*1e9)
with ExitStack() as stack:
    chain=DirectoryChain(root/'custody','fixture_directory_drift');stack.callback(chain.close)
    receiver_image=stack.enter_context(sealed_linux_executable(receiver,identity(receiver),deadline=deadline))
    guardian_image=stack.enter_context(sealed_linux_executable(guardian,identity(guardian),deadline=deadline))
    life_r,life_w=os.pipe();finish_r,finish_w=os.pipe();ack_r,ack_w=os.pipe()
    process=subprocess.Popen([str(tree),str(root),'1'],start_new_session=True,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    owner=start_durable_native_guardian(process=process,receiver=receiver_image,bootstrap=guardian_image,
        lifeline_fd=life_r,finish_fd=finish_r,ack_fd=ack_w,ack_read_fd=ack_r,
        original_directory_chain=chain,original_context_sha256='a'*64,original_launch_sha256='b'*64,
        original_profile_sha256='c'*64,deadline=deadline,deadline_ns=native_deadline)
    while not all((root/name).exists() for name in ('bootstrap.pid','descendant.pid')):
        if time.monotonic()>=deadline:raise RuntimeError('original_fixture_deadline')
        time.sleep(0.01)
    for fd in (life_r,finish_r,ack_w,ack_r):os.close(fd)
    # The sole lifeline writer stays live until actual controller process death.
    # No normal finish and no controller cleanup/finally path is executed.
    sys.stdout.buffer.write(owner.reference.canonical_bytes);sys.stdout.buffer.flush()
    os._exit(0)
'''

_FRESH_READER = r'''
import json,sys
from pathlib import Path
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.native_guardian_custody import GuardianCustodyReference,inspect_native_guardian_custody
chain=DirectoryChain(Path(sys.argv[1]),'fixture_directory_drift')
try:print(json.dumps(inspect_native_guardian_custody(GuardianCustodyReference(sys.stdin.buffer.read()),
                                                    original_directory_chain=chain)))
finally:chain.close()
'''


def test_actual_controller_exit_leaves_native_receiver_to_commit_and_fresh_process_reads(binaries, tmp_path):
    directory = tmp_path / "custody"
    directory.mkdir(mode=0o700)
    environment = {"PATH": os.defpath, "LANG": "C",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    controller = subprocess.Popen(
        [sys.executable, "-B", "-c", _CONTROLLER, str(binaries.receiver),
         str(binaries.guardian), str(binaries.tree), str(tmp_path)],
        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        original, stderr = controller.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        controller.kill()
        controller.communicate(timeout=3)
        raise
    assert controller.returncode == 0, stderr.decode()
    assert json.loads(original)["context_sha256"] == _CONTEXT
    event = directory / "guardian-event-v1.json"
    end = time.monotonic() + 3
    while time.monotonic() < end and (not event.exists() or event.stat().st_size == 0):
        time.sleep(0.01)
    assert event.exists() and event.stat().st_size > 0
    reader = subprocess.run([sys.executable, "-B", "-c", _FRESH_READER, str(directory)],
                            input=original, capture_output=True, timeout=3, env=environment, check=False)
    assert reader.returncode == 0, reader.stderr.decode()
    report = json.loads(reader.stdout)
    assert report["state"] == "watcher_exit_observed"
    assert report["native_d_observed"] is False
    assert (report["watcher_exit_kind"], report["watcher_exit_value"]) == (1, 78)
    _authority_false(report)
    # These PID files are read-only observations of this inert fixture, never
    # used to reconstruct signaling authority after controller death.
    for name in ("bootstrap.pid", "descendant.pid"):
        _inactive(int((tmp_path / name).read_text()))
    assert not (tmp_path / "late-bootstrap").exists()
    assert not (tmp_path / "late-descendant").exists()
