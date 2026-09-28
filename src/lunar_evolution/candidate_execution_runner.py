"""Execute an admitted multi-file candidate in a private workspace.

The runner is deliberately a narrow process boundary.  It revalidates the immutable admission,
source bundle bytes, and staged input bytes immediately before launch.  It never writes execution
evidence, touches Store/Candidate state, imports candidate code, or invokes an evaluator.
"""
from __future__ import annotations

import math
import os
import selectors
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain, identity
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_bundle import CandidateBundleError, verify_candidate_source_bundle
from .candidate_execution import (
    CandidateExecutionAdmission,
    CandidateExecutionError,
    admit_candidate_execution,
)
from .candidate_process_interruption import CandidateProcessInterrupted
from .candidate_workspace_plan import (
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    validate_candidate_workspace_plan,
)
from .evolution import CandidateExecution

CANDIDATE_INPUT_ROOT_ENV = "LUNAR_CANDIDATE_INPUT_ROOT"
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_RESULT_OUTPUT_BYTES = 16 * 1024
PROCESS_CLEANUP_GRACE_SECONDS = 0.25
PROCESS_READ_CHUNK_BYTES = 64 * 1024


class CandidateExecutionRunnerError(ValueError):
    """Fixed public runner failure codes without paths or OS prose."""

    _CODES = frozenset({
        "invalid", "workspace_unsafe", "input_unsafe", "plan_mismatch", "bundle_changed", "executable_unsafe",
        "bundle_mismatch", "contract_mismatch", "identity_mismatch", "budget_invalid",
        "input_changed", "process_start_failed", "process_timed_out", "output_limit_exceeded",
        "process_failed", "process_cleanup_failed",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_execution_runner_") if isinstance(code, str) else ""
        self.code = "candidate_execution_runner_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _kill_group(process: subprocess.Popen[str]) -> bool:
    try:
        os.killpg(process.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        try:
            process.kill()
            return process.poll() is not None
        except (OSError, ProcessLookupError):
            return process.poll() is not None


def _wait_owned_group_exit(pid: int, pgid: int | None) -> bool:
    """Confirm a private invocation's entire group is gone before releasing ownership."""
    if pgid != pid or pid <= 1 or pgid == os.getpgrp():
        return False
    deadline = time.monotonic() + PROCESS_CLEANUP_GRACE_SECONDS
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Some systems report EPERM while a killed group is being reaped. It remains
            # unconfirmed until ESRCH, rather than becoming proof of successful cleanup.
            pass
        except OSError:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _bounded(value: object, limit: int) -> tuple[str, bool]:
    if isinstance(value, bytes):
        raw = value
    else:
        text = value if isinstance(value, str) else ""
        raw = text.encode("utf-8", errors="replace")
    overflow = len(raw) > limit
    if overflow:
        raw = raw[:limit]
    text = raw.decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    if len(encoded) > limit:
        overflow = True
        text = encoded[:limit].decode("utf-8", errors="ignore")
    return text, overflow


def _bounded_process_bytes(
    command: list[str], *, cwd: str, environment: dict[str, str], timeout: float, output_limit: int,
    capture_limit: int, process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
    process_exit_observed: Callable[[int | None], None] | None = None,
    continuation: Callable[[], float] | None = None,
    stage: str = "candidate_execution",
) -> tuple[bytes, bytes, Literal["succeeded", "failed", "timed_out"], int | None, str | None]:
    """Run a process while keeping each captured stream bounded in memory.

    Pipes are consumed as bytes with a selector rather than through ``communicate``.  This both
    keeps output storage bounded and lets timeout/overflow cleanup stop waiting for a descendant
    that inherited the pipes.  A short post-kill grace period captures ordinary trailing output;
    pipes are then closed even if a detached descendant still holds them open. Callers validate
    the limits, including ``0 < capture_limit <= output_limit``; returned bytes are never decoded.
    """
    process: subprocess.Popen[bytes] | None = None
    process_identity: tuple[int, int | None] | None = None
    selector: selectors.BaseSelector | None = None
    streams: list[object] = []
    output = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    overflow = False
    reason: Literal["timeout", "overflow"] | None = None
    cleanup_ok = True
    owned_group_exited = True
    cleanup_deadline: float | None = None
    exit_code: int | None = None
    interruption: Exception | None = None
    released = False
    started = time.monotonic()

    def terminate() -> None:
        nonlocal cleanup_ok, cleanup_deadline
        if cleanup_deadline is not None:
            return
        cleanup_ok = _kill_group(process) if process is not None else False
        cleanup_deadline = time.monotonic() + PROCESS_CLEANUP_GRACE_SECONDS

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        # A successful start_new_session makes this exact invocation its group leader.
        # Preserve the identity even if a very short-lived child exits before getpgid.
        process_identity = (process.pid, process.pid)
        if process_observer is not None:
            try:
                process_observer(*process_identity)
            except Exception:  # noqa: BLE001, S110 - ownership metadata must not change execution
                pass
        assert process.stdout is not None and process.stderr is not None
        streams = [process.stdout, process.stderr]
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = started + timeout
        while True:
            now = time.monotonic()
            if reason is None and cleanup_deadline is None and continuation is not None:
                try:
                    remaining = continuation()
                    if type(remaining) not in (int, float) or not math.isfinite(remaining) or remaining <= 0:
                        raise CandidateExecutionRunnerError("invalid")
                    # A slow callback may return a stale remainder. Anchor it to the
                    # pre-call sample so callback work never extends the admitted deadline,
                    # then refresh now before deciding whether any work may continue.
                    deadline = min(deadline, now + remaining)
                    now = time.monotonic()
                except Exception as exc:  # noqa: BLE001 - any failed authority stops owned work
                    interruption = exc
                    terminate()
            if reason is None and interruption is None:
                if now >= deadline:
                    reason = "timeout"
                    terminate()
                elif process.poll() is not None:
                    exit_code = process.returncode
                    terminate()
            if cleanup_deadline is not None and now >= cleanup_deadline:
                if selector.get_map():
                    cleanup_ok = False
                break
            if not selector.get_map() and process.poll() is not None:
                break
            wait_for = 0.05
            if reason is None:
                wait_for = min(wait_for, max(0.0, deadline - now))
            if cleanup_deadline is not None:
                wait_for = min(wait_for, max(0.0, cleanup_deadline - now))
            for key, _ in selector.select(wait_for):
                stream_name = key.data
                try:
                    chunk = os.read(key.fileobj.fileno(), PROCESS_READ_CHUNK_BYTES)
                except (BlockingIOError, InterruptedError):
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except (KeyError, ValueError):
                        pass
                    continue
                totals[stream_name] += len(chunk)
                if len(output[stream_name]) < capture_limit:
                    remaining = capture_limit - len(output[stream_name])
                    output[stream_name].extend(chunk[:remaining])
                if totals[stream_name] > output_limit and reason is None:
                    overflow = True
                    reason = "overflow"
                    terminate()
    finally:
        if selector is not None:
            selector.close()
        for stream in streams:
            try:
                stream.close()  # type: ignore[union-attr]
            except OSError:
                pass
        if process is not None and process.poll() is None:
            cleanup_ok = _kill_group(process) and cleanup_ok
            try:
                process.wait(timeout=PROCESS_CLEANUP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    process.wait(timeout=PROCESS_CLEANUP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    cleanup_ok = False
        if process is not None and (process_observer is not None or interruption is not None):
            owned_group_exited = (
                process_identity is not None and _wait_owned_group_exit(*process_identity)
            )
            cleanup_ok = cleanup_ok and owned_group_exited
        if (process is not None and process.poll() is not None and cleanup_ok
                and process_identity is not None and process_released is not None):
            try:
                process_released(*process_identity)
                released = True
            except Exception:  # noqa: BLE001, S110 - ownership metadata must not mask the result
                pass

    if process is not None and exit_code is None and reason != "timeout":
        exit_code = process.returncode
    if process_exit_observed is not None:
        try:
            process_exit_observed(process.returncode if process is not None else None)
        except Exception:  # noqa: BLE001, S110 - telemetry cannot alter execution
            pass
    if interruption is not None:
        reason_code = (
            "cancelled" if isinstance(interruption, SolveExecutionCancelled)
            else "timed_out" if isinstance(interruption, SolveExecutionBudgetExceeded)
            else "control_failed"
        )
        assert process_identity is not None
        observation = {
            "reason": reason_code, "stage": stage, "pid": process_identity[0],
            "pgid": process_identity[1], "exit_code": process.returncode,
            "cleanup": "verified" if cleanup_ok and owned_group_exited and released else "unknown",
            "ownership_release": "observed" if released else "not_observed",
            "observed_ms": max(0, min(86_400_000, round((time.monotonic() - started) * 1000))),
        }
        raise CandidateProcessInterrupted(interruption, observation)
    stdout = bytes(output["stdout"])
    stderr = bytes(output["stderr"])
    if not owned_group_exited:
        return stdout, stderr, "failed", exit_code, "process_cleanup_failed"
    if reason == "timeout" and cleanup_ok:
        return stdout, stderr, "timed_out", None, "process_timed_out"
    if overflow:
        return stdout, stderr, "failed", exit_code, "output_limit_exceeded"
    if not cleanup_ok:
        return stdout, stderr, "failed", exit_code, "process_cleanup_failed"
    if exit_code == 0:
        return stdout, stderr, "succeeded", exit_code, None
    return stdout, stderr, "failed", exit_code, "process_failed"


def _bounded_process(
    command: list[str], *, cwd: str, environment: dict[str, str], timeout: float, output_limit: int,
    process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
    process_exit_observed: Callable[[int | None], None] | None = None,
    continuation: Callable[[], float] | None = None,
) -> tuple[str, str, Literal["succeeded", "failed", "timed_out"], int | None, str | None]:
    """Keep the candidate runner's historical bounded, replacement-decoded text projection."""
    raw_stdout, raw_stderr, status, exit_code, error = _bounded_process_bytes(
        command, cwd=cwd, environment=environment, timeout=timeout, output_limit=output_limit,
        capture_limit=min(output_limit, MAX_RESULT_OUTPUT_BYTES),
        process_observer=process_observer, process_released=process_released,
        process_exit_observed=process_exit_observed, continuation=continuation,
    )
    stdout, stdout_overflow = _bounded(raw_stdout, output_limit)
    stderr, stderr_overflow = _bounded(raw_stderr, output_limit)
    if status != "timed_out" and (stdout_overflow or stderr_overflow):
        return stdout, stderr, "failed", exit_code, "output_limit_exceeded"
    return stdout, stderr, status, exit_code, error


def _close_chain(chain: DirectoryChain) -> None:
    try:
        chain.close()
    except OSError:
        pass


def _check_chain(chain: DirectoryChain, code: str) -> None:
    try:
        chain.check()
    except (OSError, CandidateWorkspaceError):
        raise CandidateExecutionRunnerError(code) from None


def _file_snapshot(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class _Executable:
    """Hold and recheck a no-follow executable observation, without claiming atomic exec."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.chain: DirectoryChain | None = None
        self.fd: int | None = None
        try:
            self.chain = DirectoryChain(path.parent, "executable_unsafe")
            before = os.stat(path.name, dir_fd=self.chain.fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111:
                raise CandidateExecutionRunnerError("executable_unsafe")
            self.snapshot = _file_snapshot(before)
            self.fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=self.chain.fd,
            )
            self.check()
        except BaseException as exc:
            self.close()
            if isinstance(exc, (OSError, CandidateWorkspaceError)):
                raise CandidateExecutionRunnerError("executable_unsafe") from None
            raise

    def check(self) -> None:
        assert self.chain is not None and self.fd is not None
        try:
            self.chain.check()
            named = os.stat(self.path.name, dir_fd=self.chain.fd, follow_symlinks=False)
            if self.snapshot != _file_snapshot(named) or self.snapshot != _file_snapshot(os.fstat(self.fd)):
                raise CandidateExecutionRunnerError("executable_unsafe")
        except (OSError, CandidateWorkspaceError):
            raise CandidateExecutionRunnerError("executable_unsafe") from None

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.chain is not None:
            _close_chain(self.chain)


@dataclass(frozen=True)
class CandidateExecutionRun:
    """Path-free metadata returned by one admitted process invocation."""

    execution: CandidateExecution
    admission_sha256: str
    workspace_plan_sha256: str
    bundle_sha256: str
    input_count: int
    total_input_bytes: int
    entrypoint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.execution.status,
            "execution": {
                "status": self.execution.status,
                "exit_code": self.execution.exit_code,
                "duration_ms": self.execution.duration_ms,
                "stdout_bytes": self.execution.stdout_bytes,
                "stderr_bytes": self.execution.stderr_bytes,
                "error": self.execution.error,
            },
            "admission_sha256": self.admission_sha256,
            "workspace_plan_sha256": self.workspace_plan_sha256,
            "bundle_sha256": self.bundle_sha256,
            "input_count": self.input_count,
            "total_input_bytes": self.total_input_bytes,
            "entrypoint": self.entrypoint,
        }


class CandidateExecutionRunner:
    """Run a plan's explicit command against a verified workspace and input namespace."""

    def __init__(self, *, max_output_bytes: int | None = None) -> None:
        if max_output_bytes is not None and (
            isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int)
            or not 0 < max_output_bytes <= MAX_OUTPUT_BYTES
        ):
            raise CandidateExecutionRunnerError("invalid")
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        admission: CandidateExecutionAdmission | Mapping[str, object] | str | bytes,
        *,
        plan: CandidateWorkspacePlan | Mapping[str, object],
        workspace_path: str | os.PathLike[str],
        input_path: str | os.PathLike[str],
        expected_admission_sha256: str | None = None,
        expected_plan_sha256: str | None = None,
        expected_bundle_sha256: str | None = None,
        expected_contract_sha256: str | None = None,
        timeout_seconds: float | None = None,
        remaining_timeout: Callable[[str], float] | None = None,
        process_observer: Callable[[int, int | None], None] | None = None,
        process_released: Callable[[int, int | None], None] | None = None,
        process_exit_observed: Callable[[int | None], None] | None = None,
    ) -> CandidateExecutionRun:
        if remaining_timeout is not None and not callable(remaining_timeout):
            raise CandidateExecutionRunnerError("invalid")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise CandidateExecutionRunnerError("invalid")
        try:
            parsed_plan = validate_candidate_workspace_plan(
                plan if isinstance(plan, CandidateWorkspacePlan) else CandidateWorkspacePlan.from_dict(dict(plan))
            )
        except (CandidateWorkspaceError, TypeError, ValueError, KeyError, AttributeError) as exc:
            if isinstance(exc, CandidateWorkspaceError):
                raise CandidateExecutionRunnerError("plan_mismatch") from None
            raise CandidateExecutionRunnerError("invalid") from None

        def operational_timeout():
            ceiling = parsed_plan.timeout_seconds
            if timeout_seconds is not None:
                ceiling = min(ceiling, float(timeout_seconds))
            if remaining_timeout is not None:
                remaining = remaining_timeout("candidate_execution")
                if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
                        or not math.isfinite(float(remaining)) or remaining <= 0):
                    raise CandidateExecutionRunnerError("invalid")
                ceiling = min(ceiling, float(remaining))
            return ceiling

        operational_timeout()
        try:
            verified = admit_candidate_execution(
                admission,
                plan=parsed_plan,
                input_root=None,
                expected_admission_sha256=expected_admission_sha256,
                expected_plan_sha256=expected_plan_sha256,
                expected_bundle_sha256=expected_bundle_sha256,
                expected_contract_sha256=expected_contract_sha256,
            )
        except CandidateExecutionError as exc:
            suffix = exc.code.removeprefix("candidate_execution_")
            raise CandidateExecutionRunnerError("input_changed" if suffix in {"input_missing", "input_changed"} else suffix) from None
        if verified.admission.budget.max_processes != 1:
            raise CandidateExecutionRunnerError("invalid")
        try:
            workspace = absolute_path(workspace_path)
        except BenchmarkFileError:
            raise CandidateExecutionRunnerError("workspace_unsafe") from None
        try:
            inputs = absolute_path(input_path)
        except BenchmarkFileError:
            raise CandidateExecutionRunnerError("input_unsafe") from None
        environment = dict(parsed_plan.environment)
        if CANDIDATE_INPUT_ROOT_ENV in environment:
            raise CandidateExecutionRunnerError("invalid")
        environment[CANDIDATE_INPUT_ROOT_ENV] = str(inputs)
        output_limit = parsed_plan.max_output_bytes if self.max_output_bytes is None else self.max_output_bytes
        if output_limit > verified.admission.budget.max_output_bytes:
            raise CandidateExecutionRunnerError("invalid")
        with ExitStack() as resources:
            try:
                workspace_chain = DirectoryChain(workspace, "workspace_unsafe")
            except (OSError, CandidateWorkspaceError):
                raise CandidateExecutionRunnerError("workspace_unsafe") from None
            resources.callback(_close_chain, workspace_chain)
            try:
                input_chain = DirectoryChain(inputs, "input_unsafe")
            except (OSError, CandidateWorkspaceError):
                raise CandidateExecutionRunnerError("input_unsafe") from None
            resources.callback(_close_chain, input_chain)
            # Shared ordinary ancestors (for example `/` and the user's home directory) are
            # expected.  Reject only when either selected root is itself an ancestor of the
            # other, which would make the source and input namespaces overlap.
            try:
                workspace_id = identity(os.fstat(workspace_chain.fd))
                input_id = identity(os.fstat(input_chain.fd))
                workspace_ancestors = {identity(os.fstat(fd)) for fd in workspace_chain.fds}
                input_ancestors = {identity(os.fstat(fd)) for fd in input_chain.fds}
            except OSError:
                raise CandidateExecutionRunnerError("workspace_unsafe") from None
            if workspace_id in input_ancestors or input_id in workspace_ancestors:
                raise CandidateExecutionRunnerError("workspace_unsafe")
            _check_chain(workspace_chain, "workspace_unsafe")
            _check_chain(input_chain, "input_unsafe")
            # Keep an executable observation across byte verification, then recheck it together
            # with both roots immediately before launch. Popen still executes by pathname.
            command = tuple(parsed_plan.command)
            executable = _Executable(Path(command[0]))
            resources.callback(executable.close)
            try:
                verified = admit_candidate_execution(
                    verified.admission,
                    plan=parsed_plan,
                    input_root=inputs,
                    expected_admission_sha256=expected_admission_sha256,
                    expected_plan_sha256=expected_plan_sha256,
                    expected_bundle_sha256=expected_bundle_sha256,
                    expected_contract_sha256=expected_contract_sha256,
                )
            except CandidateExecutionError as exc:
                suffix = exc.code.removeprefix("candidate_execution_")
                raise CandidateExecutionRunnerError(
                    "input_changed" if suffix in {"input_missing", "input_changed"} else suffix,
                ) from None
            try:
                verify_candidate_source_bundle(
                    parsed_plan.bundle,
                    source_root=workspace,
                    contract_sha256=parsed_plan.contract_sha256,
                    expected_bundle_sha256=verified.admission.bundle_sha256,
                )
            except CandidateBundleError:
                raise CandidateExecutionRunnerError("bundle_changed") from None
            _check_chain(workspace_chain, "workspace_unsafe")
            _check_chain(input_chain, "input_unsafe")
            executable.check()
            started = time.monotonic()
            effective_timeout = operational_timeout()
            try:
                # Plan validation allows 32 command items; the entrypoint is one fixed extra.
                stdout, stderr, status, exit_code, error = _bounded_process(
                    [*command, parsed_plan.entrypoint], cwd=str(workspace), environment=environment,
                    timeout=effective_timeout, output_limit=output_limit,
                    process_observer=process_observer, process_released=process_released,
                    process_exit_observed=process_exit_observed,
                    continuation=operational_timeout if remaining_timeout is not None else None,
                )
            except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
                raise
            except OSError:
                stdout = stderr = ""
                status = "failed"
                exit_code = None
                error = "process_start_failed"
            operational_timeout()
        duration_ms = min(86_400_000, max(0, round((time.monotonic() - started) * 1000)))
        execution = CandidateExecution(status, exit_code, duration_ms, stdout, stderr, error)
        return CandidateExecutionRun(
            execution, verified.admission_sha256, parsed_plan.digest(), parsed_plan.bundle_sha256,
            verified.input_count, verified.total_input_bytes, parsed_plan.entrypoint,
        )


def run_candidate_execution(
    admission: CandidateExecutionAdmission | Mapping[str, object] | str | bytes,
    *, plan: CandidateWorkspacePlan | Mapping[str, object], workspace_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str], expected_admission_sha256: str | None = None,
    expected_plan_sha256: str | None = None, expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
    timeout_seconds: float | None = None,
    remaining_timeout: Callable[[str], float] | None = None,
    process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
    process_exit_observed: Callable[[int | None], None] | None = None,
) -> CandidateExecutionRun:
    return CandidateExecutionRunner().run(
        admission, plan=plan, workspace_path=workspace_path, input_path=input_path,
        expected_admission_sha256=expected_admission_sha256,
        expected_plan_sha256=expected_plan_sha256, expected_bundle_sha256=expected_bundle_sha256,
        expected_contract_sha256=expected_contract_sha256,
        timeout_seconds=timeout_seconds,
        remaining_timeout=remaining_timeout,
        process_observer=process_observer, process_released=process_released,
        process_exit_observed=process_exit_observed,
    )


__all__ = [
    "CANDIDATE_INPUT_ROOT_ENV",
    "CandidateExecutionRun",
    "CandidateExecutionRunner",
    "CandidateExecutionRunnerError",
    "run_candidate_execution",
]
