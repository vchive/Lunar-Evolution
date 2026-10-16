"""Local PID/PGID and inode evidence must remain fail-closed."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.external_worker_evidence import ExternalWorkerTrustProfile
from lunar_evolution.external_worker_process_evidence import (
    LocalWorkerProcessEvidenceError,
    observe_local_worker,
    process_start_identity_sha256,
)

H = "a" * 64


def _profile(pid: int, workspace: Path, transport: Path, journal: Path) -> ExternalWorkerTrustProfile:
    stat_values = [os.stat(path) for path in (workspace, transport, journal)]
    return ExternalWorkerTrustProfile(
        "fixture-project", "1", H, "b" * 64, "c" * 64, "d" * 64, "e" * 64,
        "parent-run", "task", "episode", "f" * 64, pid, os.getpgid(pid),
        process_start_identity_sha256(pid),
        stat_values[0].st_dev, stat_values[0].st_ino,
        stat_values[1].st_dev, stat_values[1].st_ino,
        stat_values[2].st_dev, stat_values[2].st_ino,
    )


def _fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    transport = tmp_path / "transport"
    transport.write_text("transport", encoding="utf-8")
    journal = tmp_path / "journal"
    journal.write_text("journal", encoding="utf-8")
    return workspace, transport, journal


def _child() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_running_observation_requires_exact_pid_group_and_inodes(tmp_path: Path) -> None:
    workspace, transport, journal = _fixtures(tmp_path)
    child = _child()
    try:
        profile = _profile(child.pid, workspace, transport, journal)
        observed = observe_local_worker(
            profile, workspace=workspace, transport=transport, journal=journal,
        )
        assert observed.status == "running"
        assert observed.process_group == "present"
        assert observed.terminal_observed is False
        assert observed.eligible_for_reconcile is False
        assert observed.workspace.matches and observed.transport.matches and observed.journal.matches
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_exited_observation_can_bind_failure_evidence(tmp_path: Path) -> None:
    workspace, transport, journal = _fixtures(tmp_path)
    child = _child()
    profile = _profile(child.pid, workspace, transport, journal)
    child.terminate()
    child.wait(timeout=5)
    observed = observe_local_worker(
        profile, workspace=workspace, transport=transport, journal=journal,
    )
    assert observed.status == "exited"
    assert observed.process_group == "absent"
    assert observed.eligible_for_reconcile
    evidence = observed.reconcile_evidence(
        unknown_checkpoint_sha256="1" * 64,
        status="failed",
        terminal_receipt_sha256="2" * 64,
    )
    assert evidence.profile_sha256 == profile.digest()
    assert evidence.controller_observed_terminal is True
    assert evidence.cleanup_confirmed is True


def test_inode_replacement_is_drifted_and_never_reconcileable(tmp_path: Path) -> None:
    workspace, transport, journal = _fixtures(tmp_path)
    child = _child()
    profile = _profile(child.pid, workspace, transport, journal)
    child.terminate()
    child.wait(timeout=5)
    workspace.rename(tmp_path / "workspace-old")
    workspace.mkdir()
    observed = observe_local_worker(
        profile, workspace=workspace, transport=transport, journal=journal,
    )
    assert observed.status == "drifted"
    assert observed.workspace.matches is False
    assert observed.eligible_for_reconcile is False
    with pytest.raises(LocalWorkerProcessEvidenceError, match="ineligible"):
        observed.reconcile_evidence(
            unknown_checkpoint_sha256="1" * 64,
            status="cancelled",
            terminal_receipt_sha256="2" * 64,
        )


def test_start_identity_drift_is_rejected_while_process_is_live(tmp_path: Path) -> None:
    workspace, transport, journal = _fixtures(tmp_path)
    child = _child()
    try:
        profile = _profile(child.pid, workspace, transport, journal)
        drifted = replace(profile, process_start_identity="0" * 64)
        observed = observe_local_worker(
            drifted, workspace=workspace, transport=transport, journal=journal,
        )
        assert observed.status == "drifted"
        assert observed.reason == "process start identity changed"
        assert observed.eligible_for_reconcile is False
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_unavailable_start_identity_does_not_fabricate_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lunar_evolution.external_worker_process_evidence._process_owner_identity",
        lambda _pid: None,
    )
    with pytest.raises(LocalWorkerProcessEvidenceError, match="identity_unavailable"):
        process_start_identity_sha256(os.getpid())
