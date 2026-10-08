"""Real Linux legacy caller cleanup after the original child has been created.

The only target is the existing local gate fixture. A wrapper completes the real
sealed owner cleanup before injecting its boundary failure or rebinding its old
borrowed number to a fixture-owned foreign file. Darwin skips are not acceptance.
"""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_producer_process import _fixture

from lunar_evolution import ProducerProcessError, producer_process, run_producer_process
from lunar_evolution.linux_executable_binding import LinuxExecutableBindingError

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires real Linux legacy child")
_CLEANUP_NOTE = "linux_execution_cleanup_unknown"


class _FixtureControlFlow(BaseException):
    pass


def _identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class _ObservedStream:
    def __init__(self, stream, role, state):
        self.stream = stream
        self.role = role
        self.state = state

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def close(self):
        self.state.stream_closes.append(self.role)
        self.stream.close()
        if self.role == "stdout" and not self.state.stream_failure_injected:
            self.state.stream_failure_injected = True
            raise OSError(errno.EIO, "inert fixture stream close")


def _observe_original_child(
    monkeypatch, tmp_path, *, boundary_failure=None, fail_stdout_close=False,
):
    real_context = producer_process.sealed_linux_executable
    real_popen = subprocess.Popen
    real_write = os.write
    foreign = tmp_path / "foreign-parent-object"
    foreign.write_bytes(b"fixture foreign descriptor remains owned by this test")
    foreign_fd = os.open(foreign, os.O_RDONLY | os.O_CLOEXEC)
    state = SimpleNamespace(
        children=[], gate_writes=[], original_cleanup_complete=False, borrowed=None,
        foreign_fd=foreign_fd, foreign_identity=_identity(foreign_fd), rebound=None,
        child_gate=None, direct_kills=[], real_child_kill=None,
        stream_closes=[], stream_failure_injected=False,
    )

    def popen(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        state.children.append(child)
        state.child_gate = int(kwargs["env"][producer_process.GATE_ENV])
        state.real_child_kill = child.kill
        if fail_stdout_close:
            child.stdout = _ObservedStream(child.stdout, "stdout", state)
            child.stderr = _ObservedStream(child.stderr, "stderr", state)

        def observed_direct_kill():
            state.direct_kills.append(child.pid)
            return state.real_child_kill()

        monkeypatch.setattr(child, "kill", observed_direct_kill)
        return child

    def write(fd, data):
        if data == b"1":
            state.gate_writes.append(fd)
        return real_write(fd, data)

    @contextmanager
    def boundary(*args, **kwargs):
        try:
            with real_context(*args, **kwargs) as live:
                state.borrowed = live.fd
                yield live
        finally:
            # Every injected failure comes after real factory cleanup, including
            # a primary ownership-capture failure thrown inside the caller body.
            assert len(state.children) == 1
            child = state.children[0]
            assert state.borrowed not in {
                foreign_fd, state.child_gate, child.stdout.fileno(), child.stderr.fileno(),
            }
            with pytest.raises(OSError) as closed:
                os.fstat(state.borrowed)
            assert closed.value.errno == errno.EBADF
            state.original_cleanup_complete = True
            os.dup2(foreign_fd, state.borrowed, inheritable=False)
            state.rebound = state.borrowed
        if boundary_failure is not None:
            raise boundary_failure

    monkeypatch.setattr(producer_process, "sealed_linux_executable", boundary)
    monkeypatch.setattr(producer_process.os, "write", write)
    return state, popen


def _assert_reaped_without_reaping_in_the_test(state):
    assert len(state.children) == 1
    child = state.children[0]
    # Calling poll()/wait() here would hide a controller that left its zombie.
    assert child.returncode is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)
    assert child.stdout.closed and child.stderr.closed


def _assert_no_gate_or_publication(state, tmp_path):
    assert state.original_cleanup_complete is True
    assert state.gate_writes == []
    batch = tmp_path / "evolution/producer-batches/journal-001"
    assert not (batch / "process-registration.json").exists()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "output/producer-result.json").exists()
    for fd in (state.foreign_fd, state.rebound):
        assert _identity(fd) == state.foreign_identity
        assert os.pread(fd, 80, 0) == b"fixture foreign descriptor remains owned by this test"


def _release_fixture_only(state):
    # A failing implementation must not leave the inert fixture alive. This uses
    # the original Popen child handle and never derives process-group authority.
    for child in state.children:
        if child.returncode is None:
            try:
                state.real_child_kill()
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
    for fd in (state.rebound, state.foreign_fd):
        if fd is None:
            continue
        try:
            if _identity(fd) == state.foreign_identity:
                os.close(fd)
        except OSError:
            pass


@pytest.mark.parametrize("failure", ["cleanup", "keyboard", "system-exit", "custom-base"])
def test_context_exit_failure_reaps_original_child_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    fault = {
        "cleanup": lambda: LinuxExecutableBindingError("linux_execution_binding_unknown"),
        "keyboard": lambda: KeyboardInterrupt("inert fixture control flow"),
        "system-exit": lambda: SystemExit("inert fixture control flow"),
        "custom-base": lambda: _FixtureControlFlow("inert fixture control flow"),
    }[failure]()
    fault.add_note(_CLEANUP_NOTE)
    state, popen = _observe_original_child(monkeypatch, tmp_path, boundary_failure=fault)
    try:
        expected = ProducerProcessError if failure == "cleanup" else type(fault)
        with pytest.raises(expected) as caught:
            run_producer_process(
                tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
                popen_factory=popen,
            )
        if failure == "cleanup":
            assert caught.value.code == "producer_process_execution_binding_unknown"
            assert caught.value.__cause__ is fault
        else:
            assert caught.value is fault
        assert caught.value.__notes__ == [_CLEANUP_NOTE]
        _assert_reaped_without_reaping_in_the_test(state)
        _assert_no_gate_or_publication(state, tmp_path)
    finally:
        _release_fixture_only(state)


@pytest.mark.parametrize("failure", ["owner-identity", "pgid-observation"])
def test_missing_group_authority_reaps_only_original_popen_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    state, popen = _observe_original_child(monkeypatch, tmp_path)
    group_signals = []

    def forbidden_group_signal(*args):
        group_signals.append(args)
        pytest.fail("missing owner observation must not create process-group signal authority")

    monkeypatch.setattr(producer_process.os, "killpg", forbidden_group_signal)
    if failure == "owner-identity":
        monkeypatch.setattr(producer_process, "_process_owner_identity", lambda _pid: None)
        expected_code = "producer_process_owner_identity_unknown"
    else:
        def unavailable_pgid(_pid):
            raise OSError(errno.EIO, "inert fixture ownership observation")

        monkeypatch.setattr(producer_process.os, "getpgid", unavailable_pgid)
        expected_code = "producer_process_registration_unknown"
    try:
        with pytest.raises(ProducerProcessError) as caught:
            run_producer_process(
                tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
                popen_factory=popen,
            )
        assert caught.value.code == expected_code
        assert caught.value.__notes__ == ["producer_process_cleanup_unknown"]
        _assert_reaped_without_reaping_in_the_test(state)
        assert state.direct_kills == [state.children[0].pid]
        assert group_signals == []
        _assert_no_gate_or_publication(state, tmp_path)
    finally:
        _release_fixture_only(state)


def test_stream_close_fault_preserves_primary_and_closes_remaining_original_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    producer_root, intent, attestation = _fixture(tmp_path)
    fault = _FixtureControlFlow("inert fixture control flow")
    state, popen = _observe_original_child(
        monkeypatch, tmp_path, boundary_failure=fault, fail_stdout_close=True,
    )
    try:
        with pytest.raises(_FixtureControlFlow) as caught:
            run_producer_process(
                tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
                popen_factory=popen,
            )
        assert caught.value is fault
        assert caught.value.__notes__ == ["producer_process_cleanup_unknown"]
        assert state.stream_failure_injected is True
        assert state.stream_closes == ["stdout", "stderr"]
        _assert_reaped_without_reaping_in_the_test(state)
        _assert_no_gate_or_publication(state, tmp_path)
    finally:
        _release_fixture_only(state)
