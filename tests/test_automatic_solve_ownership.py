"""Detached execution ownership crosses exec without a launch admission gap."""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from lunar_evolution.automatic_solve_lifecycle import (
    AutomaticSolveAlreadyRunning,
    own_automatic_solve,
)
from lunar_evolution.models import RunStatus
from lunar_evolution.store import Store


def _assert_closed(fd: int) -> None:
    with pytest.raises(OSError):
        os.fstat(fd)


def _assert_inherited_lock_has_no_gap(tmp_path: Path, *, high_stdout: bool = False) -> None:
    program = """
import os
import sys
from pathlib import Path
from lunar_evolution.automatic_solve_lifecycle import own_automatic_solve
sys.stdin.readline()
fd = int(sys.argv[2])
with own_automatic_solve('parent', Path(sys.argv[1]), inherited_fd=fd) as owner:
    assert owner.lock_fd == fd
    assert not os.get_inheritable(fd)
    print('owned', flush=True)
    sys.stdin.readline()
assert owner.lock_fd is None
"""
    process = None
    try:
        with own_automatic_solve("parent", tmp_path) as owner:
            fd = owner.lock_fd
            assert fd is not None
            process = subprocess.Popen(
                [sys.executable, "-c", program, str(tmp_path), str(fd)],
                pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
        assert owner.lock_fd is None
        _assert_closed(fd)
        # The child has not yet adopted the descriptor. Its inherited copy alone
        # preserves ownership after the launcher's context exits.
        with pytest.raises(AutomaticSolveAlreadyRunning), own_automatic_solve("parent", tmp_path):
            pytest.fail("a competing continuation entered the parent/child launch gap")
        assert process.stdin is not None and process.stdout is not None
        if high_stdout:
            fcntl = pytest.importorskip("fcntl")
            resource = pytest.importorskip("resource")
            soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
            if soft != resource.RLIM_INFINITY and soft <= 1024:
                pytest.skip("platform descriptor limit cannot represent a high stdout descriptor")
            # Duplicate one pipe, rather than exhausting the process descriptor table. Exercise
            # the same real exec/ownership handoff with a descriptor beyond select's FD_SETSIZE.
            high_fd = fcntl.fcntl(process.stdout.fileno(), fcntl.F_DUPFD_CLOEXEC, 1024)
            assert high_fd >= 1024
            process.stdout.close()
            process.stdout = os.fdopen(high_fd, "r")
        process.stdin.write("adopt\n")
        process.stdin.flush()
        with selectors.DefaultSelector() as readiness:
            readiness.register(process.stdout, selectors.EVENT_READ)
            assert readiness.select(timeout=10), "child did not adopt the lock"
        assert process.stdout.readline() == "owned\n"
        with pytest.raises(AutomaticSolveAlreadyRunning), own_automatic_solve("parent", tmp_path):
            pytest.fail("a competing continuation entered an active child")
        _, error = process.communicate("exit\n", timeout=10)
        assert process.returncode == 0, error
        with own_automatic_solve("parent", tmp_path):
            pass
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_inherited_lock_has_no_gap_after_launcher_exits(tmp_path: Path) -> None:
    _assert_inherited_lock_has_no_gap(tmp_path)


def test_inherited_lock_adoption_with_high_stdout_descriptor(tmp_path: Path) -> None:
    _assert_inherited_lock_has_no_gap(tmp_path, high_stdout=True)


def test_inherited_descriptor_is_closed_on_registry_conflict(tmp_path: Path) -> None:
    fd = os.open(tmp_path / ".automatic-solve.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with (
        own_automatic_solve("parent"),
        pytest.raises(AutomaticSolveAlreadyRunning),
        own_automatic_solve("parent", tmp_path, inherited_fd=fd),
    ):
        pytest.fail("duplicate process owner was admitted")
    _assert_closed(fd)


@pytest.mark.parametrize("invalid", ["parent", "workspace", "inode", "hardlink", "symlink"])
def test_inherited_descriptor_validation_closes_rejected_fd(tmp_path: Path, invalid: str) -> None:
    lock = tmp_path / ".automatic-solve.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    parent_id, workspace = "parent", tmp_path
    if invalid == "parent":
        parent_id = ""
    elif invalid == "workspace":
        workspace = None
    elif invalid == "inode":
        lock.unlink()
        lock.write_text("replacement")
    elif invalid == "hardlink":
        os.link(lock, tmp_path / "alias")
    else:
        lock.rename(tmp_path / "target")
        lock.symlink_to(tmp_path / "target")
    with pytest.raises(ValueError), own_automatic_solve(parent_id, workspace, inherited_fd=fd):
        pytest.fail("invalid inherited ownership was admitted")
    _assert_closed(fd)
    with own_automatic_solve("parent"):
        pass


def test_separately_opened_descriptor_cannot_impersonate_inherited_lock(tmp_path: Path) -> None:
    with own_automatic_solve("parent", tmp_path):
        fd = os.open(tmp_path / ".automatic-solve.lock", os.O_RDWR)
        with pytest.raises(AutomaticSolveAlreadyRunning), own_automatic_solve(
            "different-process-owner", tmp_path, inherited_fd=fd,
        ):
            pytest.fail("separately opened FD bypassed the existing flock")
        _assert_closed(fd)


def test_owner_exception_releases_descriptor_and_registry(tmp_path: Path) -> None:
    with (
        pytest.raises(RuntimeError, match="execution failed"),
        own_automatic_solve("parent", tmp_path) as owner,
    ):
        fd = owner.lock_fd
        assert fd is not None
        raise RuntimeError("execution failed")
    assert owner.lock_fd is None
    _assert_closed(fd)
    with own_automatic_solve("parent", tmp_path):
        pass


@pytest.mark.parametrize("invalid", [True, False, -1, 0, 1, 2, 3.0, "3"])
def test_inherited_descriptor_requires_nonstandard_integer(invalid) -> None:
    with pytest.raises(ValueError), own_automatic_solve("parent", inherited_fd=invalid):
        pytest.fail("invalid descriptor was admitted")


def test_runner_claim_has_one_winner_and_old_release_cannot_clear_replacement(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("test launch", tmp_path / "run")
    barrier = Barrier(8)

    def claim(index: int) -> tuple[int, bool]:
        barrier.wait(timeout=10)
        return index, store.claim_runner_process(run.id, 100 + index, 200 + index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(claim, range(8)))
    winners = [index for index, accepted in outcomes if accepted]
    assert len(winners) == 1
    winner = winners[0]
    assert not store.claim_runner_process(run.id, 100 + winner, 200 + winner)
    assert store.clear_runner_process(run.id, 100 + winner, 200 + winner)
    assert store.claim_runner_process(run.id, 501, 601)
    assert not store.clear_runner_process(run.id, 100 + winner, 200 + winner)
    current = store.get_run(run.id)
    assert current is not None and (current.runner_pid, current.runner_pgid) == (501, 601)


@pytest.mark.parametrize("status", list(RunStatus))
def test_runner_claim_accepts_only_runnable_parent(tmp_path: Path, status: RunStatus) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("test launch", tmp_path / "run")
    if status is RunStatus.CANCELLED:
        store.cancel_run(run.id)
    elif status is not RunStatus.PENDING:
        task = store.next_task(run.id)
        assert task is not None
        attempt = store.claim_task(task.id, "test")
        assert attempt is not None
        if status is RunStatus.AWAITING_INPUT:
            assert store.await_input(task.id, attempt.id, "question.json", "Which input?")
        elif status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            assert store.finish_task(task.id, attempt.id, status is RunStatus.SUCCEEDED)
            store.settle_run(run.id)
    assert store.get_run(run.id).status is status
    assert store.claim_runner_process(run.id, 101, 201) is (
        status in {RunStatus.PENDING, RunStatus.RUNNING}
    )
    assert not store.claim_runner_process("missing-run", 102, 202)


@pytest.mark.parametrize("pid,pgid", [(None, 201), (101, None), (101, 201)])
def test_runner_claim_preserves_any_retained_registration(tmp_path: Path, pid, pgid) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("test launch", tmp_path / "run")
    assert store.set_runner_process(run.id, pid, pgid)
    assert not store.claim_runner_process(run.id, 301, 401)
    current = store.get_run(run.id)
    assert current is not None and (current.runner_pid, current.runner_pgid) == (pid, pgid)


@pytest.mark.parametrize("invalid", [True, False, None, -1, 0, 1, 2.5, "101"])
def test_runner_claim_rejects_invalid_identity(tmp_path: Path, invalid) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("test launch", tmp_path / "run")
    with pytest.raises(ValueError):
        store.claim_runner_process(run.id, invalid, 201)
    with pytest.raises(ValueError):
        store.claim_runner_process(run.id, 101, invalid)
    current = store.get_run(run.id)
    assert current is not None and current.runner_pid is None and current.runner_pgid is None
