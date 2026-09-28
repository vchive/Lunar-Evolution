"""Retained launch intent and process telemetry for one multi-file candidate attempt.

Creating an attempt is exclusive and irreversible within this API. Existing attempts never
authorize another launch. Inspection binds local records, not evaluator acceptance or proof of
execution, and cannot repair an interrupted write.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain, identity
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_bundle import CandidateBundleError, verify_candidate_source_bundle
from .candidate_execution import CandidateExecutionError, admit_candidate_execution
from .candidate_execution_cleanup import (
    CandidateExecutionCleanupError,
    build_candidate_execution_cleanup,
    parse_candidate_execution_cleanup,
)
from .candidate_execution_runner import CandidateExecutionRunnerError, run_candidate_execution
from .candidate_process_interruption import (
    CandidateProcessInterrupted,
    build_process_interruption_receipt,
)
from .candidate_workspace_plan import (
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    validate_candidate_workspace_plan,
)

MAX_EXECUTION_RECORD_BYTES = 16 * 1024
_INTENT = "launch-intent.json"
_RESULT = "result.json"
_CLEANUP = "cleanup.json"
_COMPLETE = "completed.json"
_CORE_NAMES = {_INTENT, _RESULT, _COMPLETE}
_NAMES = _CORE_NAMES | {_CLEANUP, "interrupted.json"}
_TEMP_NAMES = {"." + name + ".tmp" for name in _NAMES}
_PROTOCOL = "lunar-candidate-execution-"
_ERRORS = {
    "process_start_failed", "process_timed_out", "output_limit_exceeded",
    "process_failed", "process_cleanup_failed",
}


class CandidateExecutionEvidenceError(ValueError):
    """Fixed, path-free error; failures never remove an allocated attempt."""

    _CODES = frozenset({
        "invalid", "plan_mismatch", "admission_mismatch", "identity_mismatch", "root_unsafe",
        "source_changed", "input_changed", "attempt_exists", "write_failed", "record_changed",
        "runner_failed",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_execution_evidence_") if isinstance(code, str) else ""
        self.code = "candidate_execution_evidence_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise CandidateExecutionEvidenceError(code)


def _encode(value: object, maximum: int = MAX_EXECUTION_RECORD_BYTES) -> bytes:
    try:
        content = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("invalid")
    if len(content) > maximum:
        _fail("invalid")
    return content


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("invalid")
    return value


def _integer(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("invalid")
    return value


def _object(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("invalid")
    return value


def _decode(content: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("invalid")
            result[key] = value
        return result
    try:
        result = json.loads(
            content.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: _fail("invalid"),
        )
        if not isinstance(result, dict) or _encode(result) != content:
            _fail("invalid")
        return result
    except (ValueError, UnicodeError, RecursionError):
        _fail("invalid")


def _node(info: os.stat_result) -> dict[str, int]:
    return {"device": _integer(info.st_dev, 2**64 - 1), "inode": _integer(info.st_ino, 2**64 - 1)}


def _validate_node(value: object) -> dict:
    item = _object(value, {"device", "inode"})
    for field in item:
        _integer(item[field], 2**64 - 1)
    return item


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (*identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink)


def _close_descriptor(descriptor: int) -> None:
    active = sys.exception()
    try:
        os.close(descriptor)
    except BaseException as failure:
        if isinstance(active, (KeyboardInterrupt, SystemExit)):
            return
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        _fail("record_changed")


def _read(chain: DirectoryChain, name: str, *, linked_temporary: bool = False) -> tuple[bytes, dict]:
    descriptor = None
    try:
        chain.check()
        before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink not in ({1, 2} if linked_temporary else {1})
                or not 0 < before.st_size <= MAX_EXECUTION_RECORD_BYTES):
            _fail("record_changed")
        if before.st_nlink == 2:
            temporary = os.stat("." + name + ".tmp", dir_fd=chain.fd, follow_symlinks=False)
            if _fingerprint(temporary) != _fingerprint(before):
                _fail("record_changed")
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=chain.fd,
        )
        if _fingerprint(before) != _fingerprint(os.fstat(descriptor)):
            _fail("record_changed")
        chunks = []
        remaining = MAX_EXECUTION_RECORD_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (len(content) != before.st_size or _fingerprint(before) != _fingerprint(after)
                or _fingerprint(after) != _fingerprint(named)):
            _fail("record_changed")
        chain.check()
        return content, {**_node(after), "size": len(content), "sha256": _sha(content)}
    except (OSError, CandidateWorkspaceError):
        _fail("record_changed")
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor)


def _write(chain: DirectoryChain, name: str, value: dict) -> tuple[bytes, dict]:
    content = _encode(value)
    temporary = "." + name + ".tmp"
    descriptor = None
    try:
        chain.check()
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=chain.fd,
        )
        os.fchmod(descriptor, 0o600)
        wanted = identity(os.fstat(descriptor))
        # A partial temporary record is retained uncertainty evidence too.
        os.fsync(chain.fd)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail("write_failed")
            view = view[written:]
        os.fsync(descriptor)
        info = os.stat(temporary, dir_fd=chain.fd, follow_symlinks=False)
        if (identity(info) != wanted or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or info.st_size != len(content)):
            _fail("record_changed")
        chain.check()
        os.link(temporary, name, src_dir_fd=chain.fd, dst_dir_fd=chain.fd, follow_symlinks=False)
        final = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        current = os.stat(temporary, dir_fd=chain.fd, follow_symlinks=False)
        if identity(final) != wanted or identity(current) != wanted:
            _fail("record_changed")
        os.unlink(temporary, dir_fd=chain.fd)
        os.fsync(chain.fd)
        found, observation = _read(chain, name)
        if found != content or (observation["device"], observation["inode"]) != wanted:
            _fail("record_changed")
        return found, observation
    except (OSError, CandidateWorkspaceError):
        _fail("write_failed")
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor)


def _request(admission, plan, pins):
    try:
        parsed = validate_candidate_workspace_plan(
            plan if isinstance(plan, CandidateWorkspacePlan) else CandidateWorkspacePlan.from_dict(dict(plan)),
        )
    except (CandidateWorkspaceError, TypeError, ValueError, AttributeError, RecursionError):
        _fail("plan_mismatch")
    try:
        verified = admit_candidate_execution(admission, plan=parsed, **pins)
    except CandidateExecutionError:
        _fail("admission_mismatch")
    binding = {
        "workspace_plan_sha256": parsed.digest(), "admission_sha256": verified.admission_sha256,
        "bundle_sha256": parsed.bundle_sha256, "contract_sha256": parsed.contract_sha256,
        "source_file_table_sha256": parsed.file_table_sha256,
        "input_file_table_sha256": _sha(_encode(
            [item.to_dict() for item in verified.admission.inputs], 128 * 1024,
        )),
    }
    return parsed, verified.admission, binding


def _open(value) -> tuple[Path, DirectoryChain]:
    try:
        path = absolute_path(value)
        return path, DirectoryChain(path, "destination_changed")
    except (OSError, BenchmarkFileError, CandidateWorkspaceError):
        _fail("root_unsafe")


def _close_handles(handles: list[DirectoryChain]) -> None:
    active = sys.exception()
    failure = None
    for handle in reversed(handles):
        try:
            handle.close()
        except BaseException as exc:  # noqa: BLE001 - release remaining handles during interruption
            if failure is None or isinstance(exc, (KeyboardInterrupt, SystemExit)):
                failure = exc
    if isinstance(active, (KeyboardInterrupt, SystemExit)):
        return  # preserve the active interruption after best-effort release
    if isinstance(failure, (KeyboardInterrupt, SystemExit)):
        raise failure
    if failure is not None:
        _fail("record_changed")


def _disjoint(first: DirectoryChain, second: DirectoryChain) -> None:
    first_ids = {identity(os.fstat(fd)) for fd in first.fds}
    second_ids = {identity(os.fstat(fd)) for fd in second.fds}
    if identity(os.fstat(first.fd)) in second_ids or identity(os.fstat(second.fd)) in first_ids:
        _fail("root_unsafe")


def _result(value, plan, admission) -> dict:
    expected = {
        "admission_sha256": admission.digest(), "workspace_plan_sha256": plan.digest(),
        "bundle_sha256": plan.bundle_sha256, "input_count": len(admission.inputs),
        "total_input_bytes": sum(item.size for item in admission.inputs), "entrypoint": plan.entrypoint,
    }
    item = _object(value, {*expected, "status", "execution"})
    if any(type(item[key]) is not type(wanted) or item[key] != wanted for key, wanted in expected.items()):
        _fail("identity_mismatch")
    execution = _object(item["execution"], {
        "status", "exit_code", "duration_ms", "stdout_bytes", "stderr_bytes", "error",
    })
    status = execution["status"]
    error = execution["error"]
    if not isinstance(status, str) or status not in {"succeeded", "failed", "timed_out"} or item["status"] != status:
        _fail("invalid")
    code = execution["exit_code"]
    if code is not None and (type(code) is not int or not -(2**31) <= code < 2**31):
        _fail("invalid")
    if error is not None and (not isinstance(error, str) or error not in _ERRORS):
        _fail("invalid")
    if ((status == "succeeded" and (code != 0 or error is not None))
            or (status == "timed_out" and (code is not None or error != "process_timed_out"))
            or (status == "failed" and (error is None or error == "process_timed_out"))):
        _fail("invalid")
    _integer(execution["duration_ms"], 86_400_000)
    for key in ("stdout_bytes", "stderr_bytes"):
        _integer(execution[key], 16 * 1024)
    return _decode(_encode(item))


def _probe_process_group(identity_pair: tuple[int, int] | None) -> str:
    """Probe one observed private process group without signaling it."""
    if identity_pair is None:
        return "unknown"
    _pid, pgid = identity_pair
    if type(pgid) is not int or pgid <= 1 or pgid == os.getpgrp():
        return "unknown"
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "absent"
    except PermissionError:
        return "unknown"
    except OSError as exc:
        return "absent" if exc.errno == errno.ESRCH else "unknown"
    return "present"


def _cleanup_payload(
    returned, observed: list[tuple[int, int | None]], released: list[tuple[int, int | None]],
    exits: list[int | None], observed_ms: int, *, callbacks_succeeded: bool = True,
) -> dict:
    """Construct an observation from supervisor callbacks and a post-return group probe."""
    observer = observed[0] if len(observed) == 1 and observed[0][1] is not None else None
    release = released[0] if len(released) == 1 and released[0][1] is not None else None
    observer_identity = (
        {"pid": observer[0], "pgid": observer[1]} if observer is not None else None
    )
    release_identity = (
        {"pid": release[0], "pgid": release[1]} if release is not None else None
    )
    probe = _probe_process_group((observer[0], observer[1]) if observer is not None else None)
    release_state = (
        "observed" if release is not None else ("not_observed" if observed else "unknown")
    )
    native_exit = returned.execution.exit_code
    process_exit = exits[0] if len(exits) == 1 else None
    verified = (
        observer_identity is not None and release_identity == observer_identity
        and probe == "absent" and len(exits) == 1
        and native_exit is not None and process_exit == native_exit
        and callbacks_succeeded
    )
    cleanup = "verified" if verified else ("failed" if probe == "present" else "unknown")
    return {
        "protocol": "lunar-candidate-execution-cleanup-v1", "schema_version": "1",
        "launch_intent_sha256": "0" * 64, "result_sha256": "0" * 64,
        "native_exit_code": native_exit, "process_exit_code": process_exit,
        "observer_identity": observer_identity, "release_identity": release_identity,
        "group_probe": probe, "ownership_release": release_state,
        "cleanup": cleanup, "observed_ms": max(0, min(86_400_000, observed_ms)),
    }


@dataclass(frozen=True)
class CandidateExecutionRecord:
    """Detached, path-free observation; it grants no launch or evaluation authority."""

    status: str
    launch_intent_sha256: str | None = None
    result_sha256: str | None = None
    completion_sha256: str | None = None
    runner_result_sha256: str | None = None
    _result_json: bytes | None = None
    cleanup_sha256: str | None = None
    _cleanup_json: bytes | None = None

    def to_dict(self) -> dict:
        result = {"status": self.status}
        for key in (
            "launch_intent_sha256", "result_sha256", "completion_sha256", "runner_result_sha256",
            "cleanup_sha256",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self._result_json is not None:
            result["runner_result"] = json.loads(self._result_json)
        if self._cleanup_json is not None:
            cleanup = json.loads(self._cleanup_json)
            # Process IDs are private supervisor evidence.  Keep only the bounded status in
            # this detached projection; the retained receipt remains available to the inspector.
            result["cleanup"] = cleanup["cleanup"]
        return result

    @property
    def cleanup_status(self) -> str:
        """Return the retained cleanup claim, or unknown for legacy v1 records."""
        if self._cleanup_json is None:
            return "unknown"
        return json.loads(self._cleanup_json)["cleanup"]


def _names(chain: DirectoryChain) -> set[str]:
    chain.check()
    names = set()
    with os.scandir(chain.fd) as entries:
        for entry in entries:
            if entry.name not in _NAMES | _TEMP_NAMES or entry.name in names:
                _fail("record_changed")
            if not entry.is_file(follow_symlinks=False):
                _fail("record_changed")
            names.add(entry.name)
    chain.check()
    return names


def _inspect(chain: DirectoryChain, plan, admission, binding) -> CandidateExecutionRecord:
    names = _names(chain)
    if _INTENT not in names:
        if names - {"." + _INTENT + ".tmp"}:
            _fail("record_changed")
        return CandidateExecutionRecord("uncertain")
    intent_bytes, intent_descriptor = _read(
        chain, _INTENT, linked_temporary="." + _INTENT + ".tmp" in names,
    )
    intent = _object(_decode(intent_bytes), {
        "protocol", "schema_version", "binding", "workspace_identity", "input_identity",
        "attempt_identity", "nonce",
    })
    if (intent["protocol"] != _PROTOCOL + "launch-intent-v1" or intent["schema_version"] != "1"
            or intent["binding"] != binding or intent["attempt_identity"] != _node(os.fstat(chain.fd))):
        _fail("identity_mismatch")
    _digest(intent["nonce"])
    nodes = [_validate_node(intent[field]) for field in ("workspace_identity", "input_identity", "attempt_identity")]
    if len({(node["device"], node["inode"]) for node in nodes}) != 3:
        _fail("identity_mismatch")
    intent_sha = _sha(intent_bytes)
    # An interruption receipt can never coexist with authoritative completion. Do not allow
    # adding result/completion files after a stop to turn a cancelled attempt into a success.
    if "interrupted.json" in names and (_RESULT in names or _COMPLETE in names):
        _fail("record_changed")
    if names & _TEMP_NAMES or not _CORE_NAMES <= names:
        if _COMPLETE in names and _RESULT not in names:
            _fail("record_changed")
        chain.check()
        return CandidateExecutionRecord("uncertain", intent_sha)
    result_bytes, result_descriptor = _read(chain, _RESULT)
    result = _object(_decode(result_bytes), {
        "protocol", "schema_version", "launch_intent_sha256", "runner_result", "runner_result_sha256",
    })
    metadata = _result(result["runner_result"], plan, admission)
    result_sha = _sha(_encode(metadata))
    if (result["protocol"] != _PROTOCOL + "result-v1" or result["schema_version"] != "1"
            or result["launch_intent_sha256"] != intent_sha or result["runner_result_sha256"] != result_sha):
        _fail("identity_mismatch")
    cleanup_bytes = cleanup_descriptor = None
    cleanup = None
    if _CLEANUP in names:
        cleanup_bytes, cleanup_descriptor = _read(chain, _CLEANUP)
        try:
            cleanup = parse_candidate_execution_cleanup(
                _decode(cleanup_bytes),
                expected_launch_intent_sha256=intent_sha,
                expected_result_sha256=_sha(result_bytes),
            )
        except CandidateExecutionCleanupError:
            _fail("identity_mismatch")
        # The companion receipt must describe the same native outcome. A timed-out process may
        # have a later OS return code after the runner has deliberately kept its public exit
        # unknown; retain that distinction while rejecting forged normal exits.
        execution = metadata["execution"]
        if cleanup["native_exit_code"] != execution["exit_code"]:
            _fail("identity_mismatch")
        if execution["status"] != "timed_out" and cleanup["process_exit_code"] != execution["exit_code"]:
            _fail("identity_mismatch")
    complete_bytes, complete_descriptor = _read(chain, _COMPLETE)
    complete = _decode(complete_bytes)
    expected = {
        "protocol": _PROTOCOL + "completion-v1", "schema_version": "1",
        "launch_intent": intent_descriptor, "result": result_descriptor,
    }
    if cleanup_descriptor is not None:
        expected["cleanup"] = cleanup_descriptor
    if _encode(expected) != complete_bytes or complete != expected:
        _fail("identity_mismatch")
    # Re-read every retained record after comparison; same-byte replacement changes identity too.
    retained = [
        (_INTENT, intent_bytes, intent_descriptor), (_RESULT, result_bytes, result_descriptor),
        (_COMPLETE, complete_bytes, complete_descriptor),
    ]
    if cleanup_bytes is not None and cleanup_descriptor is not None:
        retained.insert(2, (_CLEANUP, cleanup_bytes, cleanup_descriptor))
    for name, content, descriptor in retained:
        if _read(chain, name) != (content, descriptor):
            _fail("record_changed")
    if _names(chain) != names:
        _fail("record_changed")
    return CandidateExecutionRecord(
        status="recorded", launch_intent_sha256=intent_sha, result_sha256=_sha(result_bytes),
        completion_sha256=_sha(complete_bytes), runner_result_sha256=result_sha,
        _result_json=_encode(metadata), cleanup_sha256=(
            cleanup["receipt_sha256"] if cleanup is not None else None
        ), _cleanup_json=(cleanup_bytes if cleanup_bytes is not None else None),
    )


def inspect_candidate_execution_record(
    attempt_path: str | os.PathLike[str], *, plan, admission,
    expected_admission_sha256: str | None = None, expected_plan_sha256: str | None = None,
    expected_bundle_sha256: str | None = None, expected_contract_sha256: str | None = None,
    expected_completion_sha256: str | None = None,
) -> CandidateExecutionRecord:
    """Read and bind an existing record; incomplete attempts remain uncertain without repair."""
    pins = {
        "expected_admission_sha256": expected_admission_sha256, "expected_plan_sha256": expected_plan_sha256,
        "expected_bundle_sha256": expected_bundle_sha256, "expected_contract_sha256": expected_contract_sha256,
    }
    parsed, admitted, binding = _request(admission, plan, pins)
    if expected_completion_sha256 is not None:
        _digest(expected_completion_sha256)
    _, chain = _open(attempt_path)
    try:
        result = _inspect(chain, parsed, admitted, binding)
        if expected_completion_sha256 is not None and result.completion_sha256 != expected_completion_sha256:
            _fail("identity_mismatch")
        return result
    except (OSError, CandidateWorkspaceError):
        _fail("record_changed")
    finally:
        _close_handles([chain])


def run_candidate_execution_recorded(
    admission, *, plan, workspace_path: str | os.PathLike[str], input_path: str | os.PathLike[str],
    attempt_path: str | os.PathLike[str], expected_admission_sha256: str | None = None,
    expected_plan_sha256: str | None = None, expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
    timeout_seconds: float | None = None,
    remaining_timeout=None,
    process_observer=None,
    process_released=None,
) -> CandidateExecutionRecord:
    """Reserve a new attempt, persist intent, invoke the runner once, and bind its telemetry."""
    pins = {
        "expected_admission_sha256": expected_admission_sha256, "expected_plan_sha256": expected_plan_sha256,
        "expected_bundle_sha256": expected_bundle_sha256, "expected_contract_sha256": expected_contract_sha256,
    }
    parsed, admitted, binding = _request(admission, plan, pins)
    handles = []
    try:
        workspace, source_chain = _open(workspace_path)
        handles.append(source_chain)
        inputs, input_chain = _open(input_path)
        handles.append(input_chain)
        _disjoint(source_chain, input_chain)
        destination = absolute_path(attempt_path)
        _, parent_chain = _open(destination.parent)
        handles.append(parent_chain)
        # Parent can be a shared ancestor, but cannot itself lie inside source or input.
        for chain in (source_chain, input_chain):
            if identity(os.fstat(chain.fd)) in {identity(os.fstat(fd)) for fd in parent_chain.fds}:
                _fail("root_unsafe")
        try:
            admit_candidate_execution(admitted, plan=parsed, input_root=inputs, **pins)
        except CandidateExecutionError:
            _fail("input_changed")
        try:
            verify_candidate_source_bundle(parsed.bundle, source_root=workspace, contract_sha256=parsed.contract_sha256)
        except CandidateBundleError:
            _fail("source_changed")
        for chain in handles:
            chain.check()
        try:
            os.mkdir(destination.name, 0o700, dir_fd=parent_chain.fd)
        except FileExistsError:
            _fail("attempt_exists")
        # Never remove an allocated attempt, including failures before intent publication.
        allocated = os.stat(destination.name, dir_fd=parent_chain.fd, follow_symlinks=False)
        if not stat.S_ISDIR(allocated.st_mode):
            _fail("record_changed")
        os.fsync(parent_chain.fd)
        _, attempt_chain = _open(destination)
        handles.append(attempt_chain)
        if identity(allocated) != identity(os.fstat(attempt_chain.fd)):
            _fail("record_changed")
        os.fchmod(attempt_chain.fd, 0o700)
        for chain in (source_chain, input_chain):
            _disjoint(chain, attempt_chain)
        intent = {
            "protocol": _PROTOCOL + "launch-intent-v1", "schema_version": "1", "binding": binding,
            "workspace_identity": _node(os.fstat(source_chain.fd)),
            "input_identity": _node(os.fstat(input_chain.fd)),
            "attempt_identity": _node(os.fstat(attempt_chain.fd)), "nonce": secrets.token_hex(32),
        }
        intent_bytes, intent_descriptor = _write(attempt_chain, _INTENT, intent)
        for chain in handles:
            chain.check()
        if (_names(attempt_chain) != {_INTENT}
                or _read(attempt_chain, _INTENT) != (intent_bytes, intent_descriptor)):
            _fail("record_changed")
        # The runner performs its own launch-time source/input and executable preflight.
        observed_processes: list[tuple[int, int | None]] = []
        released_processes: list[tuple[int, int | None]] = []
        observed_exits: list[int | None] = []
        callbacks_succeeded = True

        def observe_process(pid: int, pgid: int | None) -> None:
            nonlocal callbacks_succeeded
            observed_processes.append((pid, pgid))
            if process_observer is not None:
                try:
                    process_observer(pid, pgid)
                except Exception:  # noqa: BLE001 - caller telemetry cannot alter execution
                    callbacks_succeeded = False

        def release_process(pid: int, pgid: int | None) -> None:
            nonlocal callbacks_succeeded
            if process_released is not None:
                try:
                    process_released(pid, pgid)
                except Exception:  # noqa: BLE001 - caller telemetry cannot alter execution
                    callbacks_succeeded = False
                    return
            released_processes.append((pid, pgid))

        def observe_exit(exit_code: int | None) -> None:
            observed_exits.append(exit_code)

        cleanup_started = time.monotonic()
        try:
            returned = run_candidate_execution(
                admitted, plan=parsed, workspace_path=workspace, input_path=inputs, **pins,
                timeout_seconds=timeout_seconds,
                remaining_timeout=remaining_timeout,
                process_observer=observe_process,
                process_released=release_process,
                process_exit_observed=observe_exit,
            )
        except CandidateProcessInterrupted as stop:
            payload = build_process_interruption_receipt(
                stop.observation, request_sha256=_sha(intent_bytes), stage="candidate_execution",
            )
            _write(attempt_chain, "interrupted.json", payload)
            raise stop.cause
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception:  # noqa: BLE001 - runner exceptions cannot expose candidate or host prose
            _fail("runner_failed")
        for chain in handles:
            chain.check()
        if _read(attempt_chain, _INTENT) != (intent_bytes, intent_descriptor):
            _fail("record_changed")
        metadata = _result(returned.to_dict(), parsed, admitted)
        if remaining_timeout is not None:
            remaining_timeout("candidate_execution")
        result_bytes, result_descriptor = _write(attempt_chain, _RESULT, {
            "protocol": _PROTOCOL + "result-v1", "schema_version": "1",
            "launch_intent_sha256": _sha(intent_bytes), "runner_result": metadata,
            "runner_result_sha256": _sha(_encode(metadata)),
        })
        cleanup = _cleanup_payload(
            returned, observed_processes, released_processes, observed_exits,
            round((time.monotonic() - cleanup_started) * 1000),
            callbacks_succeeded=callbacks_succeeded,
        )
        cleanup["launch_intent_sha256"] = _sha(intent_bytes)
        cleanup["result_sha256"] = _sha(result_bytes)
        _, cleanup_descriptor = _write(
            attempt_chain, _CLEANUP,
            build_candidate_execution_cleanup(
                cleanup,
                expected_launch_intent_sha256=_sha(intent_bytes),
                expected_result_sha256=_sha(result_bytes),
            ),
        )
        _write(attempt_chain, _COMPLETE, {
            "protocol": _PROTOCOL + "completion-v1", "schema_version": "1",
            "launch_intent": intent_descriptor, "result": result_descriptor,
            "cleanup": cleanup_descriptor,
        })
        record = _inspect(attempt_chain, parsed, admitted, binding)
        if record.status != "recorded":
            _fail("record_changed")
        return record
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except CandidateExecutionRunnerError:
        _fail("runner_failed")
    except BenchmarkFileError:
        _fail("root_unsafe")
    except CandidateWorkspaceError:
        _fail("record_changed")
    except OSError:
        _fail("write_failed")
    except CandidateExecutionEvidenceError:
        raise
    except Exception:  # noqa: BLE001 - malformed in-memory results use fixed public errors too
        _fail("invalid")
    finally:
        _close_handles(handles)


__all__ = [
    "CandidateExecutionEvidenceError", "CandidateExecutionRecord",
    "inspect_candidate_execution_record", "run_candidate_execution_recorded",
]
