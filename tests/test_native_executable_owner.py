from __future__ import annotations

import os
import sys
from contextlib import contextmanager

import pytest
from test_native_trusted_attempt import _attempt
from test_producer_process import _fixture as _producer_fixture

from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution import producer_process
from lunar_evolution.linux_executable_binding import LinuxSealedExecutable

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original executable handoff")


def _hold_pair(monkeypatch):
    state = {}
    real = runner.prepare_trusted_executable_pair

    @contextmanager
    def remember(*args, **kwargs):
        with real(*args, **kwargs) as pair:
            state["pair"] = pair
            state["fds"] = pair.pass_fds
            yield pair

    monkeypatch.setattr(runner, "prepare_trusted_executable_pair", remember)
    return state


def _run(values):
    workspace, producer, intent, attestation, artifact, _batch = values
    return runner.run_native_trusted_attempt(
        workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact,
    )


def _assert_refused(result, batch):
    assert result.reason == "trusted_binding_owner_invalid"
    assert not result.target_started
    assert not (batch / "work" / "marker").exists()


def test_original_pair_checks_and_parent_only_anchors_through_real_v2(tmp_path, monkeypatch):
    import lunar_evolution.linux_executable_binding as executable

    values = _attempt(tmp_path)
    state = _hold_pair(monkeypatch)
    anchors, checks, inherited = [], [], []
    real_create, real_check, real_spawn = executable.os.memfd_create, runner._validate_original_linux_executable_pair, runner.subprocess.Popen

    def create(*args, **kwargs):
        fd = real_create(*args, **kwargs)
        anchors.append(fd)
        return fd

    def check(pair):
        real_check(pair)
        checks.append(pair)

    class Spawn(real_spawn):
        def __init__(self, *args, **kwargs):
            passed = set(kwargs["pass_fds"])
            assert not (passed & set(anchors))
            inherited.append(passed)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(executable.os, "memfd_create", create)
    monkeypatch.setattr(runner, "_validate_original_linux_executable_pair", check)
    monkeypatch.setattr(runner.subprocess, "Popen", Spawn)
    result = _run(values)
    assert result.target_started and result.exit_code == 0
    assert len(checks) == 3 and all(pair is state["pair"] for pair in checks)
    assert len(anchors) == 2 and len(inherited) == 2
    assert set(state["fds"]) <= inherited[0]
    assert state["pair"].bootstrap.pass_fd in inherited[1]
    for fd in (*anchors, *state["fds"]):
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("role", ["bootstrap", "target"])
def test_drift_before_control_encoding_never_spawns(tmp_path, monkeypatch, role):
    values = _attempt(tmp_path)
    real = runner.prepare_trusted_executable_pair

    @contextmanager
    def drift(*args, **kwargs):
        with real(*args, **kwargs) as pair:
            object.__setattr__(getattr(pair, role), "executable", "/foreign")
            yield pair

    monkeypatch.setattr(runner, "prepare_trusted_executable_pair", drift)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("must refuse before spawn"))
    _assert_refused(_run(values), values[-1])


def test_drift_after_control_encoding_is_rechecked_before_popen(tmp_path, monkeypatch):
    values = _attempt(tmp_path)
    state = _hold_pair(monkeypatch)
    real_command = runner.native_bootstrap_command

    def command(*args, **kwargs):
        command = real_command(*args, **kwargs)
        object.__setattr__(state["pair"].target.snapshot, "sha256", "b" * 64)
        return command

    monkeypatch.setattr(runner, "native_bootstrap_command", command)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("must recheck before spawn"))
    _assert_refused(_run(values), values[-1])


@pytest.mark.parametrize("role", ["bootstrap", "target"])
def test_drift_after_bootstrap_spawn_blocks_guardian_and_reaps_original(tmp_path, monkeypatch, role):
    values = _attempt(tmp_path)
    state = _hold_pair(monkeypatch)
    processes = []
    real_spawn = runner.subprocess.Popen

    class Spawn(real_spawn):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            processes.append(self)
            object.__setattr__(getattr(state["pair"], role).snapshot, "size", 0)

    monkeypatch.setattr(runner.subprocess, "Popen", Spawn)
    monkeypatch.setattr(runner, "start_native_guardian", lambda **kw: pytest.fail("drift must prevent guardian spawn"))
    _assert_refused(_run(values), values[-1])
    assert len(processes) == 1 and processes[0].poll() is not None
    for fd in state["fds"]:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_legacy_pre_spawn_check_rejects_manufactured_live_handle(tmp_path, monkeypatch):
    producer, intent, attestation = _producer_fixture(tmp_path)

    @contextmanager
    def detached(*args, **kwargs):
        yield LinuxSealedExecutable(31, intent.executable_sha256, intent.executable_size)

    monkeypatch.setattr(producer_process, "sealed_linux_executable", detached)
    with pytest.raises(producer_process.ProducerProcessError, match="^producer_process_execution_binding_unknown$"):
        producer_process.run_producer_process(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer,
            popen_factory=lambda *a, **kw: pytest.fail("detached handle must not spawn"),
        )
