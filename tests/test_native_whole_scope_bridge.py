"""Explicit custody mode/FD forwarding, without starting an installed supervisor."""
from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest
from test_native_whole_scope_custody import original as original  # noqa: PLC0414

from lunar_evolution import native_whole_scope as whole
from lunar_evolution.producer_bootstrap import TrustedBootstrapLaunch
from lunar_evolution.producer_launcher import ProducerLaunchIntent


@pytest.mark.parametrize("original,selected", [
    ("linux-whole-scope-private-custody-v1", None),
    ("linux-whole-scope-private-custody-v1", "linux-whole-scope-private-custody-v1"),
    ("linux-whole-scope-private-custody-v2", "linux-whole-scope-private-custody-v2"),
    ("linux-whole-scope-private-custody-v3", "linux-whole-scope-private-custody-v3"),
], indirect=["original"])
def test_original_start_forwards_explicit_mode_and_only_original_custody_fd(original, selected, monkeypatch):
    owner, custody, _path = original
    custody_fd = custody._directory
    if selected is None:
        owner._custody_owner = None
    process = object.__new__(subprocess.Popen)
    process._child_created = False
    process.returncode = None
    process.pid = 123
    launch = object.__new__(TrustedBootstrapLaunch)
    object.__setattr__(launch, "intent_sha256", "1" * 64)
    object.__setattr__(launch, "launch_sha256", "2" * 64)
    intent = object.__new__(ProducerLaunchIntent)
    object.__setattr__(intent, "executable_sha256", "3" * 64)
    owner._final_intent = launch.intent_sha256
    owner._channels_prepared = True
    for name in ("_profile_fd", "_delegation_fd", "_image_fd"):
        setattr(owner, name, owner._own(os.open(os.devnull, os.O_RDONLY)))
    owner._controller, owner._controller_child = owner._socket_pair()
    owner._enrollment, owner._enrollment_child = owner._socket_pair()
    owner._lifecycle, owner._lifecycle_child = owner._socket_pair()
    reader, writer = os.pipe()
    owner._own(reader)
    owner._own(writer)
    observations = []
    original_listdir = whole.os.listdir
    monkeypatch.setattr(whole.os, "listdir", lambda path: [str(os.getpid())]
                        if path == "/proc/self/task" else original_listdir(path))
    monkeypatch.setattr(whole.threading, "active_count", lambda: 1)
    monkeypatch.setattr(whole.signal, "getsignal", lambda _signal: whole.signal.SIG_DFL)
    # Only native invocation is intercepted. Actual custody owner acquisition,
    # private directory FD borrowing, pipes and channel retirement remain real.
    monkeypatch.setattr(whole.os, "pidfd_open", lambda *_a: os.dup(reader))
    monkeypatch.setattr(whole.subprocess, "Popen", lambda command, **kwargs:
                        observations.append((command, kwargs)) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(owner, "_send", lambda *a, **k: observations.append((a, k)))
    owner.start_original(process=process, launch=launch, intent=intent,
                         controller_lifeline_fd=reader, deadline_ns=owner.deadline_ns)
    command, kwargs = observations[0]
    expected_mode = ({"linux-whole-scope-private-custody-v2": "--supervisor-custody-v2",
                      "linux-whole-scope-private-custody-v3": "--supervisor-custody-v3"}
                     .get(selected, "--supervisor-v1"))
    assert command[1] == expected_mode
    assert command[command.index("--custody-dir-fd") + 1] == str(custody_fd if selected else -1)
    assert (custody_fd in kwargs["pass_fds"]) == bool(selected)
    assert kwargs["close_fds"] is True
    assert kwargs["executable"] == command[0] == f"/proc/self/fd/{owner._image_fd}"
    assert len(observations) == 2
    assert custody._started == bool(selected)
