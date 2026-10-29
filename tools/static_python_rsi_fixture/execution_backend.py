"""Pinned local build-process mechanism, separate from the mock build driver.

This module can execute a reviewed recipe, but supplies no CPython recipe and
makes no source acquisition, configured closure, installation or runtime claim.
It is an installer mechanism for trusted tools, not a subprocess sandbox.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from tools.static_python_rsi_fixture.build_driver import (
    STAGES,
    ControlledBuildError,
    _preparation_wire,
)
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation

RECIPE_SCHEMA = "lunar-static-python-pinned-execution-recipe-v1"
RECIPE_V2_SCHEMA = "lunar-static-python-pinned-execution-recipe-v2"
RECIPE_V3_SCHEMA = "lunar-static-python-pinned-execution-recipe-v3"
RECIPE_V4_SCHEMA = "lunar-static-python-pinned-execution-recipe-v4"
INPUT_PROJECTION_V4 = "source-data-static-tools-v1"
INPUT_PROJECTION = INPUT_PROJECTION_V4
MAX_V3_RECIPE_BYTES = 8 * 1024 * 1024
MAX_V3_INPUT_RECORDS = 32768
MAX_RECIPE_BYTES = 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_INPUT_BYTES = 4 * 1024 * 1024 * 1024
MAX_INPUT_FILE_BYTES = MAX_INPUT_BYTES
_ENV_KEYS = frozenset({
    "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "CC", "AR", "RANLIB", "CFLAGS",
    "CPPFLAGS", "LDFLAGS", "CONFIG_SITE",
})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class BuildExecutionError(RuntimeError):
    """Fixed refusal carrying retained, detached attempt evidence when available."""

    def __init__(self, code: str, *, report: BuildExecutionReport | None = None,
                 failure_detail: Mapping[str, Any] | None = None) -> None:
        self.code = "static_python_build_execution_" + code
        self.report = report
        self.failure_detail = (report.failure_detail if report is not None else
                               _freeze(dict(failure_detail)) if failure_detail is not None else None)
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class BuildExecutionReport:
    """Process observations only; successful commands do not close installation."""

    recipe_sha256: str
    completed_stages: tuple[str, ...]
    stage_evidence: tuple[Mapping[str, Any], ...]
    status: str
    reason: str | None
    configured_closure_verified: bool = False
    installation_accepted: bool = False
    runtime_execution_performed: bool = False
    production_admission: bool = False
    failure_detail: Mapping[str, Any] | None = None
    persistence_error: Mapping[str, Any] | None = None


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _fail(code: str, *, failure_detail: Mapping[str, Any] | None = None) -> None:
    raise BuildExecutionError(code, failure_detail=failure_detail)


def _io_detail(error: OSError, *, operation: str, stage: str | None = None,
               command_index: int | None = None) -> dict[str, Any]:
    """Retain bounded causes without arbitrary exception messages or paths."""
    return {"stage": stage, "command_index": command_index, "operation": operation,
            "errno": error.errno if type(error.errno) is int else None}


def _path(value: object) -> str:
    if (type(value) is not str or not 0 < len(value) <= 512
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(char in value for char in "\\\x00:\n\r")
            or any(ord(char) < 32 or ord(char) > 126 for char in value)):
        _fail("path_invalid")
    return value


def _finite(value: object) -> bool:
    return ((type(value) is int and -(2**63) <= value < 2**63)
            or (type(value) is float and math.isfinite(value)))


def _pin(value: object) -> None:
    if (type(value) is not str or _DIGEST.fullmatch(value) is None
            or value in {"0" * 64, "f" * 64}):
        _fail("pin_invalid")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("recipe_duplicate_key")
        result[key] = value
    return result


def _directory_reference(arg: str, known: dict[str, set[str]], available: set[str]) -> bool:
    if not arg.startswith(("@source-dir/", "@toolchain-dir/", "@work-dir/")):
        return False
    role, relative = arg[1:].split("/", 1)
    path = _path(relative)
    records = available if role == "work-dir" else known[role.removesuffix("-dir")]
    if not any(record.startswith(path + "/") for record in records):
        _fail("directory_reference_not_available")
    return True


def _v2_stages(value: object, known: dict[str, set[str]], executable: set[str],
               *, version3: bool = False) -> None:
    """Check the whole ordered graph before any workspace mutation or process.

    These sets describe only prospective dependencies. Runtime dispatch grants a
    generated executable separately, after all of its command's outputs pass
    readback and the existing input/output drift checks.
    """
    if type(value) is not list or len(value) != len(STAGES):
        _fail("stages_invalid")
    command_bound = 512 if version3 else 256
    output_bound = 1024 if version3 else 256
    argv_bound = 512 if version3 else 256
    available: set[str] = set()
    total_commands = 0
    for stage, name in zip(value, STAGES, strict=True):
        if (type(stage) is not dict or set(stage) != {"stage", "commands"}
                or stage["stage"] != name):
            _fail("stage_invalid")
        commands = stage["commands"]
        if type(commands) is not list or not 0 < len(commands) <= command_bound:
            _fail("commands_invalid")
        total_commands += len(commands)
        output_count = 0
        for command in commands:
            if type(command) is not dict or set(command) != {"argv", "outputs"}:
                _fail("command_invalid")
            outputs = command["outputs"]
            if type(outputs) is not list or not 0 < len(outputs) <= output_bound:
                _fail("outputs_invalid")
            output_count += len(outputs)
            if output_count > output_bound:
                _fail("output_budget_exceeded")
            current: set[str] = set()
            for record in outputs:
                if (type(record) is not dict
                        or set(record) != {"path", "max_size", "executable"}
                        or type(record["max_size"]) is not int
                        or not 0 < record["max_size"] <= MAX_OUTPUT_BYTES
                        or type(record["executable"]) is not bool):
                    _fail("output_record_invalid")
                path = _path(record["path"])
                if path in available or path in current:
                    _fail("output_duplicate")
                if any(path.startswith(other + "/") or other.startswith(path + "/")
                       for other in available | current):
                    _fail("output_path_overlap")
                current.add(path)
            argv = command["argv"]
            if (type(argv) is not list or not 0 < len(argv) <= argv_bound
                    or any(type(arg) is not str or not 0 < len(arg) <= 4096 or "\x00" in arg
                           for arg in argv)):
                _fail("argv_invalid")
            if argv[0] not in executable:
                _fail("executable_not_pinned")
            for arg in argv:
                if not arg.startswith("@"):
                    continue
                if version3 and _directory_reference(arg, known, available | current):
                    continue
                parts = arg[1:].split("/", 1)
                if len(parts) != 2 or parts[0] not in {"source", "toolchain", "work"}:
                    _fail("reference_invalid")
                role, path = parts[0], _path(parts[1])
                if role == "work":
                    if path not in available and path not in current:
                        _fail("reference_not_available")
                elif path not in known[role]:
                    _fail("reference_not_pinned")
            available.update(current)
            executable.update("@work/" + record["path"] for record in outputs if record["executable"])
    if total_commands > (1024 if version3 else 512):
        _fail("command_budget_exceeded")


def _recipe(raw: bytes, expected_sha256: str, *, version3: bool = False,
            version4: bool = False) -> dict[str, Any]:
    if version3 and version4:
        _fail("recipe_shape_invalid")
    extended = version3 or version4
    _pin(expected_sha256)
    if (type(raw) is not bytes or not 0 < len(raw) <= (MAX_V3_RECIPE_BYTES if extended else MAX_RECIPE_BYTES)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        _fail("recipe_pin_mismatch")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs)
        canonical = _canonical(value)
    except BuildExecutionError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        value = None
        canonical = None
    if canonical != raw:
        _fail("recipe_noncanonical")
    if (type(value) is not dict
            or set(value) != ({"schema", "preparation_sha256", "inputs", "environment", "stages"}
                              | ({"input_projection"} if version4 else set()))
            or type(value["schema"]) is not str
            or value["schema"] not in ({RECIPE_V4_SCHEMA} if version4 else
                                      {RECIPE_V3_SCHEMA} if version3 else {RECIPE_SCHEMA, RECIPE_V2_SCHEMA})
            or version4 and value["input_projection"] != INPUT_PROJECTION_V4):
        _fail("recipe_shape_invalid")
    command_outputs = value["schema"] in {RECIPE_V2_SCHEMA, RECIPE_V3_SCHEMA, RECIPE_V4_SCHEMA}
    _pin(value["preparation_sha256"])
    inputs = value["inputs"]
    if type(inputs) is not dict or set(inputs) != {"source", "toolchain"}:
        _fail("inputs_invalid")
    known: dict[str, set[str]] = {}
    executable: set[str] = set()
    total = 0
    for role in ("source", "toolchain"):
        records = inputs[role]
        if type(records) is not list or not 0 < len(records) <= (MAX_V3_INPUT_RECORDS if extended else 16384):
            _fail("input_inventory_invalid")
        known[role] = set()
        for record in records:
            if (type(record) is not dict
                    or set(record) != {"path", "size", "sha256", "executable"}
                    or type(record["size"]) is not int
                    or not 0 <= record["size"] <= MAX_INPUT_FILE_BYTES
                    or type(record["executable"]) is not bool):
                _fail("input_record_invalid")
            path = _path(record["path"])
            _pin(record["sha256"])
            if path in known[role]:
                _fail("input_duplicate")
            known[role].add(path)
            total += record["size"]
            if record["executable"] and not (version4 and role == "source"):
                executable.add("@" + role + "/" + path)
        if [item["path"] for item in records] != sorted(known[role]):
            _fail("input_order_invalid")
    if total > MAX_INPUT_BYTES:
        _fail("input_budget_exceeded")
    env = value["environment"]
    if (type(env) is not dict or not set(env) <= _ENV_KEYS
            or any(type(item) is not str or len(item) > 4096 or "\x00" in item
                   for item in env.values())):
        _fail("environment_invalid")
    for item in env.values():
        if item.startswith("@"):
            if extended and _directory_reference(item, known, set()):
                continue
            parts = item[1:].split("/", 1)
            if len(parts) != 2 or parts[0] not in {"source", "toolchain", "work"}:
                _fail("reference_invalid")
            role, path = parts[0], _path(parts[1])
            if command_outputs and role == "work":
                # Recipe environment is installed before the first command.
                _fail("reference_not_available")
            if role != "work" and path not in known[role]:
                _fail("reference_not_pinned")
    if command_outputs:
        _v2_stages(value["stages"], known, executable, version3=extended)
        return value
    stages = value["stages"]
    if type(stages) is not list or len(stages) != 4:
        _fail("stages_invalid")
    available_outputs: set[str] = set()
    total_commands = 0
    for stage, name in zip(stages, STAGES, strict=True):
        if (type(stage) is not dict or set(stage) != {"stage", "commands", "outputs"}
                or stage["stage"] != name):
            _fail("stage_invalid")
        commands = stage["commands"]
        if type(commands) is not list or not 0 < len(commands) <= 256:
            _fail("commands_invalid")
        total_commands += len(commands)
        for argv in commands:
            if (type(argv) is not list or not 0 < len(argv) <= 256
                    or any(type(arg) is not str or not 0 < len(arg) <= 4096 or "\x00" in arg
                           for arg in argv)):
                _fail("argv_invalid")
            if argv[0] not in executable:
                _fail("executable_not_pinned")
            for arg in argv:
                if arg.startswith("@"):
                    parts = arg[1:].split("/", 1)
                    if len(parts) != 2 or parts[0] not in {"source", "toolchain", "work"}:
                        _fail("reference_invalid")
                    role, path = parts[0], _path(parts[1])
                    if role != "work" and path not in known[role]:
                        _fail("reference_not_pinned")
        outputs = stage["outputs"]
        if type(outputs) is not list or not 0 < len(outputs) <= 256:
            _fail("outputs_invalid")
        for record in outputs:
            if (type(record) is not dict
                    or set(record) != {"path", "max_size", "executable"}
                    or type(record["max_size"]) is not int
                    or not 0 < record["max_size"] <= MAX_OUTPUT_BYTES
                    or type(record["executable"]) is not bool):
                _fail("output_record_invalid")
            path = _path(record["path"])
            if path in available_outputs:
                _fail("output_duplicate")
            available_outputs.add(path)
            if record["executable"]:
                executable.add("@work/" + path)
    if total_commands > 512:
        _fail("command_budget_exceeded")
    return value


def _open_beneath(root: Path, relative: str) -> int:
    """Open regular input/output bytes without following any path component."""
    absolute = root.absolute()
    current = os.open(absolute.anchor, _DIR_FLAGS)
    try:
        for part in absolute.parts[1:] + tuple(relative.split("/")[:-1]):
            child = os.open(part, _DIR_FLAGS, dir_fd=current)
            os.close(current)
            current = child
        return os.open(relative.split("/")[-1], _READ_FLAGS, dir_fd=current)
    finally:
        os.close(current)


def _observe(root: Path, relative: str, maximum: int, *, destination: Path | None = None,
             executable: bool | None = None,
             checkpoint: Callable[[], None] | None = None) -> dict[str, Any]:
    if checkpoint is not None:
        checkpoint()
    fd = _open_beneath(root, relative)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            _fail("file_invalid")
        if executable is not None and bool(before.st_mode & 0o111) is not executable:
            _fail("file_mode_mismatch")
        digest = hashlib.sha256()
        count = 0
        output = None
        try:
            if destination is not None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                output = destination.open("xb")
            while True:
                if checkpoint is not None:
                    checkpoint()
                block = os.read(fd, 65536)
                if checkpoint is not None:
                    checkpoint()
                if not block:
                    break
                count += len(block)
                if count > maximum:
                    _fail("file_budget_exceeded")
                digest.update(block)
                if output is not None:
                    output.write(block)
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
        finally:
            if output is not None:
                output.close()
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or count != before.st_size):
            _fail("file_drift")
        return {"path": relative, "size": count, "sha256": digest.hexdigest(),
                "executable": bool(before.st_mode & 0o111)}
    finally:
        os.close(fd)


def _write_once(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _prepare_v2_outputs(work: Path, outputs: list[dict[str, Any]],
                        checkpoint: Callable[[], None]) -> None:
    """Create only declared parent directories, refusing every existing leaf.

    This is preparation in the already fresh trusted-tool workspace, not a new
    custody or sandbox mechanism. No prior file is removed or followed.
    """
    for output in outputs:
        checkpoint()
        descriptor = os.open(work, _DIR_FLAGS)
        try:
            parts = output["path"].split("/")
            for part in parts[:-1]:
                checkpoint()
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, _DIR_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            try:
                os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                _fail("output_not_fresh")
        finally:
            os.close(descriptor)


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def _command(argv: list[str], *, work: Path, environment: dict[str, str], logs: Path,
             checkpoint: Callable[[], None], evidence: dict[str, Any],
             stage: str | None = None, command_index: int | None = None) -> None:
    process = None
    failure = None
    sizes = {"stdout": 0, "stderr": 0}
    digests = {key: hashlib.sha256() for key in sizes}
    evidence.update({"status": "partial", "returncode": None, "direct_child_reaped": False})
    operation = "command.logs.open"
    try:
        with (logs / "stdout.log").open("xb") as stdout_log, \
                (logs / "stderr.log").open("xb") as stderr_log, selectors.DefaultSelector() as selector:
            checkpoint()
            operation = "command.spawn"
            process = subprocess.Popen(
                argv, cwd=work, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                start_new_session=True, close_fds=True,
            )
            operation = "command.pipes.prepare"
            for stream, name, output in (
                (process.stdout, "stdout", stdout_log), (process.stderr, "stderr", stderr_log),
            ):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, (name, output))
            while selector.get_map() or process.poll() is None:
                checkpoint()
                operation = "command.pipes.select"
                for key, _ in selector.select(timeout=0.02):
                    operation = "command.log.read"
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    name, output = key.data
                    permitted = min(len(block), MAX_LOG_BYTES - sum(sizes.values()))
                    operation = "command.log.write"
                    output.write(block[:permitted])
                    sizes[name] += permitted
                    digests[name].update(block[:permitted])
                    if permitted < len(block):
                        _fail("log_budget_exceeded")
            operation = "command.wait"
            evidence["returncode"] = process.wait(timeout=5)
            checkpoint()
            if evidence["returncode"] != 0:
                _fail("command_failed")
            evidence["status"] = "complete"
            for output in (stdout_log, stderr_log):
                operation = "command.log.flush"
                output.flush()
                operation = "command.log.fsync"
                os.fsync(output.fileno())
            operation = "command.resources.close"
    except BuildExecutionError as exc:
        failure = exc.code.removeprefix("static_python_build_execution_")
    except KeyboardInterrupt:
        failure = "interrupted"
    except OSError as exc:
        failure = "command_io_failure"
        evidence["failure_detail"] = _io_detail(
            exc, operation=operation, stage=stage, command_index=command_index,
        )
    except Exception:  # noqa: BLE001 - arbitrary tool/path details remain out of errors
        failure = "command_io_failure"
    finally:
        if process is not None:
            try:
                # A reaped PID may have been reused. Signal only a still-owned
                # live direct child; exit without wait leaves its PID unreusable.
                if process.poll() is None:
                    _kill_and_reap(process)
                evidence["direct_child_reaped"] = True
            except Exception:  # noqa: BLE001 - retain uncertainty, never success
                failure = "cleanup_unknown"
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        evidence["descendant_cleanup_verified"] = False
        evidence["logs"] = {name: {"size": sizes[name], "sha256": digests[name].hexdigest()}
                            for name in sizes}
    if failure is not None:
        evidence["status"] = "partial"
        evidence["reason"] = failure
        _fail(failure, failure_detail=evidence.get("failure_detail"))


def _run_pinned_build(
    preparation: RSIProfilePreparation,
    *,
    recipe_bytes: bytes,
    expected_recipe_sha256: str,
    source_root: Path,
    toolchain_root: Path,
    workspace: Path,
    deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    version3: bool = False,
    version4: bool = False,
    custody_backend: str | None = None,
    vfs_roots: bool = False,
) -> BuildExecutionReport:
    """Execute pinned tools with no ambient environment or installation promotion.

    Callers must authorize the actual build separately. No default execution
    recipe or opt-in environment variable bypasses unresolved CPython closure.
    The recipe pin is an integrity comparison, not acquisition/authentication or
    authority to run tools. Passing this API does not establish G1/G2 acceptance.
    """
    preparation_invalid = False
    try:
        _preparation_wire(preparation)
    except ControlledBuildError:
        preparation_invalid = True
    if preparation_invalid:
        _fail("preparation_invalid")
    recipe = _recipe(recipe_bytes, expected_recipe_sha256, version3=version3, version4=version4)
    extended = version3 or version4
    command_outputs = recipe["schema"] in {RECIPE_V2_SCHEMA, RECIPE_V3_SCHEMA, RECIPE_V4_SCHEMA}
    custody_prefix = None
    source_data_backend = ("podman-snapshots-source-data-vfs-v1" if vfs_roots
                           else "podman-snapshots-source-data-v2")
    if type(vfs_roots) is not bool or vfs_roots and not version4:
        _fail("custody_backend")
    if version4 and custody_backend != source_data_backend:
        _fail("custody_backend")
    if custody_backend is not None:
        if (type(custody_backend) is not str
                or custody_backend not in ({source_data_backend} if version4 else
                                           {"podman", "podman-snapshots-v1"})
                or not extended):
            _fail("custody_backend")
        from tools.static_python_rsi_fixture.command_input_graph import (
            validate_dependency_command_graph,
            validate_dependency_command_graph_v4,
        )
        from tools.static_python_rsi_fixture.podman_custody import (
            preflight_podman_custody,
            validate_custody_image_budget,
            validate_snapshot_budget,
        )
        (validate_dependency_command_graph_v4 if version4 else validate_dependency_command_graph)(recipe)
        if custody_backend in {"podman-snapshots-v1", source_data_backend}:
            validate_snapshot_budget(recipe)
        else:
            validate_custody_image_budget(recipe)
        custody_prefix = preflight_podman_custody()
    if recipe["preparation_sha256"] != hashlib.sha256(preparation.wire_bytes).hexdigest():
        _fail("preparation_pin_mismatch")
    if (not _finite(deadline) or deadline <= 0
            or not callable(monotonic) or (interrupted is not None and not callable(interrupted))):
        _fail("control_invalid")
    if any(type(path) is not Path and not isinstance(path, Path)
           for path in (source_root, toolchain_root, workspace)):
        _fail("root_invalid")
    roots = {"source": source_root.absolute(), "toolchain": toolchain_root.absolute()}
    destination = workspace.absolute()
    if any(destination == root or destination in root.parents or root in destination.parents
           for root in roots.values()):
        _fail("workspace_overlaps_input")
    for path in (destination.parent, *roots.values()):
        if path.resolve() != path or not path.is_dir():
            _fail("root_invalid")
    completed: list[str] = []
    stages: list[dict[str, Any]] = []

    def checkpoint() -> None:
        failure = None
        now, stop = None, None
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
        except KeyboardInterrupt:
            failure = "interrupted"
        except Exception:  # noqa: BLE001 - trusted callback exceptions are normalized
            failure = "control_failure"
        if failure is not None:
            _fail(failure)
        if not _finite(now) or type(stop) is not bool:
            _fail("control_invalid")
        if stop:
            _fail("interrupted")
        if now >= deadline:
            _fail("deadline_expired")

    checkpoint()
    workspace_reason = None
    failure_detail = None
    try:
        destination.mkdir()
    except OSError as exc:
        workspace_reason = "workspace_not_fresh" if isinstance(exc, FileExistsError) else "workspace_io_failure"
        failure_detail = _io_detail(exc, operation="workspace.mkdir")
    if workspace_reason is not None:
        # No successful create-only claim: do not persist into this path.
        report = BuildExecutionReport(
            recipe_sha256=expected_recipe_sha256, completed_stages=(), stage_evidence=(),
            status="partial", reason=workspace_reason, failure_detail=_freeze(failure_detail),
        )
        raise BuildExecutionError(workspace_reason, report=report) from None
    reason = None
    active_stage = None
    active_command = None
    operation = "recipe.write"
    try:
        _write_once(destination / "recipe.json", recipe_bytes)
        operation = "attempt.write"
        _write_once(destination / "attempt.json", _canonical({
            "schema": "lunar-static-python-build-attempt-v1", "recipe_sha256": expected_recipe_sha256,
            "status": "started", "production_admission": False,
        }))
        snapshots = {role: destination / role for role in roots}
        work = destination / "work"
        operation = "work.mkdir"
        work.mkdir()
        operation = "home.mkdir"
        (work / ".home").mkdir()
        for role, records in recipe["inputs"].items():
            operation = "snapshot.mkdir"
            snapshots[role].mkdir()
            for record in records:
                checkpoint()
                target = snapshots[role] / record["path"]
                operation = "snapshot.copy"
                observed = _observe(roots[role], record["path"], MAX_INPUT_FILE_BYTES,
                                    destination=target, executable=record["executable"],
                                    checkpoint=checkpoint)
                if observed != record:
                    _fail("input_pin_mismatch")
                operation = "snapshot.chmod"
                target.chmod(0o555 if record["executable"] else 0o444)
                operation = "snapshot.verify"
                if _observe(snapshots[role], record["path"], MAX_INPUT_FILE_BYTES,
                            checkpoint=checkpoint) != record:
                    _fail("snapshot_pin_mismatch")
        locations = {**snapshots, "work": work}

        def expand(arg: str) -> str:
            if not arg.startswith("@"):
                return arg
            role, relative = arg[1:].split("/", 1)
            return str(locations[role.removesuffix("-dir") if extended else role] / relative)

        environment = {key: expand(value) for key, value in recipe["environment"].items()}
        environment.update({"PATH": str(snapshots["toolchain"] / "bin"),
                            "HOME": str(work / ".home"), "TMPDIR": str(work)})
        if extended:
            # Zig can create only attempt-local caches; never use ambient caches.
            environment.update({"ZIG_GLOBAL_CACHE_DIR": str(work / ".zig-global-cache"),
                                "ZIG_LOCAL_CACHE_DIR": str(work / ".zig-local-cache"),
                                "ZIG_LIB_DIR": str(snapshots["toolchain"] / "lib")})
        custody = None
        if custody_prefix is not None:
            from tools.static_python_rsi_fixture.podman_custody import PodmanCustody
            operation = "custody.prepare"
            custody_options = {"snapshot_mounts": custody_backend in {
                "podman-snapshots-v1", source_data_backend}}
            if version4:
                custody_options["source_data"] = True
            if vfs_roots:
                custody_options["vfs_roots"] = True
            custody = PodmanCustody(destination=destination, prefix=custody_prefix,
                                     recipe_sha256=expected_recipe_sha256, checkpoint=checkpoint,
                                     **custody_options)
        retained_outputs: list[dict[str, Any]] = []
        observed_executables = {
            "@" + role + "/" + record["path"]
            for role, records in recipe["inputs"].items()
            for record in records if record["executable"] and not (version4 and role == "source")
        }

        def verify_inputs() -> None:
            for role, records in recipe["inputs"].items():
                for record in records:
                    checkpoint()
                    if (_observe(roots[role], record["path"], MAX_INPUT_FILE_BYTES,
                                 checkpoint=checkpoint) != record
                            or _observe(snapshots[role], record["path"], MAX_INPUT_FILE_BYTES,
                                        checkpoint=checkpoint) != record):
                        _fail("input_drift")
            for record in retained_outputs:
                checkpoint()
                if _observe(work, record["path"], MAX_OUTPUT_BYTES,
                            checkpoint=checkpoint) != record:
                    _fail("output_drift")

        for stage in recipe["stages"]:
            active_stage = stage["stage"]
            active_command = None
            operation = "inputs.verify"
            verify_inputs()
            evidence = {"stage": stage["stage"], "status": "partial", "commands": [], "outputs": []}
            stages.append(evidence)
            for index, command in enumerate(stage["commands"]):
                active_command = index
                argv = command["argv"] if command_outputs else command
                operation = "inputs.verify"
                verify_inputs()
                if command_outputs:
                    if argv[0] not in observed_executables:
                        _fail("executable_not_observed")
                    operation = "outputs.prepare"
                    _prepare_v2_outputs(work, command["outputs"], checkpoint)
                log_dir = destination / "logs" / stage["stage"] / str(index)
                operation = "logs.mkdir"
                log_dir.mkdir(parents=True)
                command_evidence: dict[str, Any] = {"index": index}
                evidence["commands"].append(command_evidence)
                operation = "command.execute"
                if custody is None:
                    _command([expand(arg) for arg in argv], work=work, environment=environment,
                             logs=log_dir, checkpoint=checkpoint, evidence=command_evidence,
                             stage=active_stage, command_index=index)
                else:
                    custody.run(argv, inputs=recipe["inputs"], snapshots=snapshots, prior=retained_outputs,
                                outputs=command["outputs"], work=work, environment=recipe["environment"],
                                logs=log_dir, evidence=command_evidence, stage=stage["stage"], index=index)
                if command_outputs:
                    # A zero process status is insufficient to grant generated tools.
                    command_evidence["status"] = "partial"
                    command_evidence["outputs"] = []
                operation = "inputs.verify"
                verify_inputs()
                if command_outputs:
                    produced = command_evidence["outputs"]
                    for output in command["outputs"]:
                        checkpoint()
                        operation = "outputs.observe"
                        produced.append(_observe(
                            work, output["path"], output["max_size"],
                            executable=output["executable"], checkpoint=checkpoint,
                        ))
                    retained_outputs.extend(produced)
                    # Verify the entire group, all previous outputs and original
                    # inputs again before a later command may consume any tool.
                    operation = "inputs.verify"
                    verify_inputs()
                    evidence["outputs"].extend(produced)
                    observed_executables.update(
                        "@work/" + output["path"] for output in produced if output["executable"]
                    )
                    command_evidence["status"] = "complete"
            active_command = None
            if not command_outputs:
                for output in stage["outputs"]:
                    checkpoint()
                    operation = "outputs.observe"
                    observed = _observe(work, output["path"], output["max_size"],
                                        executable=output["executable"], checkpoint=checkpoint)
                    evidence["outputs"].append(observed)
                    retained_outputs.append(observed)
            operation = "inputs.verify"
            verify_inputs()
            evidence["status"] = "complete"
            completed.append(stage["stage"])
        checkpoint()
    except BuildExecutionError as exc:
        reason = exc.code.removeprefix("static_python_build_execution_")
        if exc.failure_detail is not None:
            failure_detail = {**exc.failure_detail, "stage": active_stage,
                              "command_index": active_command}
    except KeyboardInterrupt:
        reason = "interrupted"
    except OSError as exc:
        reason = "attempt_io_failure"
        failure_detail = _io_detail(
            exc, operation=operation, stage=active_stage, command_index=active_command,
        )
    except Exception:  # noqa: BLE001 - preserve partial workspace without leaking paths
        reason = "attempt_io_failure"
    payload = {
        "schema": "lunar-static-python-build-execution-report-v5" if vfs_roots else
                  "lunar-static-python-build-execution-report-v4" if version4 else
                  "lunar-static-python-build-execution-report-v3" if version3 else
                  "lunar-static-python-build-execution-report-v2" if command_outputs else
                  "lunar-static-python-build-execution-report-v1",
        "recipe_sha256": expected_recipe_sha256, "completed_stages": completed,
        "stage_evidence": stages, "status": "complete" if reason is None else "partial",
        "reason": reason, "configured_closure_verified": False, "installation_accepted": False,
        "runtime_execution_performed": False, "production_admission": False,
    }
    if version4:
        payload.update(input_projection=INPUT_PROJECTION_V4,
                       immutable_custody_verified=False, driver_inputs_verified=False,
                       implicit_link_inputs_verified=False, online_publication=False)
    if vfs_roots:
        payload["custody_backend"] = source_data_backend
    if failure_detail is not None:
        payload["failure_detail"] = dict(failure_detail)
    report = BuildExecutionReport(
        recipe_sha256=expected_recipe_sha256, completed_stages=tuple(completed),
        stage_evidence=tuple(_freeze(item) for item in stages), status=payload["status"], reason=reason,
        failure_detail=_freeze(dict(failure_detail)) if failure_detail is not None else None,
    )
    persistence_error = None
    try:
        _write_once(destination / "report.json", _canonical(payload))
    except OSError as exc:
        persistence_error = _io_detail(exc, operation="report.write")
    if persistence_error is not None:
        reason = reason or "report_write_failed"
        report = replace(report, status="partial", reason=reason,
                         persistence_error=_freeze(persistence_error))
    if reason is not None:
        raise BuildExecutionError(reason, report=report) from None
    return report


def run_pinned_build(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> BuildExecutionReport:
    """Original v1/v2 mechanism with its original bounds and reference grammar."""
    return _run_pinned_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic,
    )


def run_pinned_build_v3(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str | None = None,
) -> BuildExecutionReport:
    """Explicit full-toolchain mechanism; optional custody grants no admission.

    ``custody_backend="podman"`` selects the same loop's fixed Linux custody
    dispatch. ``podman-snapshots-v1`` uses the same checks with fixed read-only
    snapshot mounts. The default and v1/v2 retain ordinary-copy behavior.
    """
    return _run_pinned_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic, version3=True,
        custody_backend=custody_backend,
    )


def run_pinned_build_v4(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-v2",
) -> BuildExecutionReport:
    """Explicit source-as-data view within the original single-attempt lifecycle."""
    return _run_pinned_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic, version4=True,
        custody_backend=custody_backend,
    )


def run_pinned_build_v4_vfs(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-vfs-v1",
) -> BuildExecutionReport:
    """Explicit VFS acquisition, preserving recipe-v4 and the original budget."""
    return _run_pinned_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic, version4=True,
        custody_backend=custody_backend, vfs_roots=True,
    )


__all__ = [
    "INPUT_PROJECTION",
    "INPUT_PROJECTION_V4",
    "RECIPE_SCHEMA",
    "RECIPE_V2_SCHEMA",
    "RECIPE_V3_SCHEMA",
    "RECIPE_V4_SCHEMA",
    "BuildExecutionError",
    "BuildExecutionReport",
    "run_pinned_build",
    "run_pinned_build_v3",
    "run_pinned_build_v4",
    "run_pinned_build_v4_vfs",
]
