"""Run the existing build mechanism and consume its actual pinned outputs.

Caller-supplied output inventories are not an execution input. This consumer
uses the original runner's report, persisted report bytes and FD readback of
every input/output before comparing actual compiler/linker depfiles. Ordinary
workspace copies remain ordinary copies: no immutable custody or admission is
granted, and unknown driver/cache inputs cannot be learned into the inventory.
"""

from __future__ import annotations

import hashlib
import os
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tools.static_python_rsi_fixture.command_input_graph import (
    validate_dependency_command_graph,
    validate_dependency_command_graph_v4,
)
from tools.static_python_rsi_fixture.dependency_capture import (
    SOURCE_DIRECTORY_PROFILE,
    CompilerDependencyError,
    compare_compiler_dependencies,
    compare_compiler_dependencies_v4,
    compare_compiler_dependencies_v4_source_directories,
)
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    MAX_INPUT_FILE_BYTES,
    BuildExecutionError,
    BuildExecutionReport,
    _finite,
    _open_beneath,
    run_pinned_build_v3,
    run_pinned_build_v4,
    run_pinned_build_v4_vfs,
    run_pinned_build_v4_vfs_lifetime,
    run_pinned_build_v4_vfs_retained,
)
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.link_dependency_capture import (
    LinkDependencyError,
    compare_linker_dependencies,
    compare_linker_dependencies_v4,
    validate_dependency_capture_plan,
    validate_dependency_capture_plan_v4,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.standalone_linker import verify_standalone_linker_input
from tools.static_python_rsi_fixture.zig_lld_linker import verify_zig_lld_linker_input


class BuildDependencyError(RuntimeError):
    """A fixed failure retaining the original execution report when available."""

    def __init__(self, reason: str, *, execution_report: BuildExecutionReport | None = None):
        self.code = "build_dependency_" + reason
        self.execution_report = execution_report
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class DependencyCheckedBuild:
    """Actual local execution and depfile comparison, never an accepted image."""

    execution_report: BuildExecutionReport
    evidence_sha256: str
    compiler_comparison_sha256: str
    linker_comparison_sha256: str
    output_inventory_sha256: str
    immutable_custody_verified: bool = False
    driver_inputs_verified: bool = False
    implicit_link_inputs_verified: bool = False
    installation_accepted: bool = False
    production_admission: bool = False
    online_publication: bool = False


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if type(value) in {list, tuple}:
        return [_plain(item) for item in value]
    return value


def _signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_pin(root: Path, record: dict, checkpoint: Callable[[], None], *, retain=False) -> bytes:
    """Read only through no-follow FDs and compare the original report's pin."""
    checkpoint()
    fd = _open_beneath(root, record["path"])
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size != record["size"]
                or bool(before.st_mode & 0o111) is not record["executable"]):
            raise BuildDependencyError("file_pin")
        digest, count, blocks = hashlib.sha256(), 0, []
        while True:
            checkpoint()
            block = os.read(fd, 65536)
            checkpoint()
            if not block:
                break
            count += len(block)
            if count > record["size"] or count > MAX_INPUT_FILE_BYTES:
                raise BuildDependencyError("file_pin")
            digest.update(block)
            if retain:
                blocks.append(block)
        if (count != record["size"] or digest.hexdigest() != record["sha256"]
                or _signature(before) != _signature(os.fstat(fd))):
            raise BuildDependencyError("file_pin")
        # A replacement path with equal bytes is still a different readback.
        repeated = _open_beneath(root, record["path"])
        try:
            if _signature(os.fstat(repeated)) != _signature(before):
                raise BuildDependencyError("file_changed")
        finally:
            os.close(repeated)
        checkpoint()
        return b"".join(blocks)
    finally:
        os.close(fd)


def _report_outputs(report: BuildExecutionReport, recipe: dict,
                    custody_backend: str | None = None, *, version4: bool = False,
                    workspace: Path | None = None, checkpoint: Callable[[], None] | None = None,
                    vfs_roots: bool = False,
                    vfs_retained: bool = False,
                    vfs_lifetime: bool = False,
                    ) -> tuple[bytes, list[dict]]:
    source_data_backend = ("podman-snapshots-source-data-vfs-lifetime-v1" if vfs_lifetime else
                           "podman-snapshots-source-data-vfs-retained-v1" if vfs_retained else
                           "podman-snapshots-source-data-vfs-v1" if vfs_roots
                           else "podman-snapshots-source-data-v2")
    if (type(vfs_roots) is not bool or vfs_roots and not version4
            or type(vfs_retained) is not bool or vfs_retained and not (version4 and vfs_roots)
            or type(vfs_lifetime) is not bool or vfs_lifetime and not (version4 and vfs_roots and vfs_retained)):
        raise BuildDependencyError("custody_backend")
    if version4 and (custody_backend != source_data_backend or workspace is None):
        raise BuildDependencyError("custody_backend")
    if (type(report) is not BuildExecutionReport or report.status != "complete"
            or report.reason is not None or report.completed_stages != ("configure", "freeze", "compile", "link")
            or report.recipe_sha256 != hashlib.sha256(canonical(recipe)).hexdigest()
            or any(getattr(report, key) is not False for key in (
                "configured_closure_verified", "installation_accepted",
                "runtime_execution_performed", "production_admission"))):
        raise BuildDependencyError("execution_report")
    stages = _plain(report.stage_evidence)
    if len(stages) != len(recipe["stages"]):
        raise BuildDependencyError("execution_report")
    records = []
    prior = []
    for stage, planned in zip(stages, recipe["stages"], strict=True):
        if (stage.get("stage") != planned["stage"] or stage.get("status") != "complete"
                or len(stage.get("commands", [])) != len(planned["commands"])):
            raise BuildDependencyError("execution_report")
        group = []
        for index, (command, expected) in enumerate(zip(stage["commands"], planned["commands"], strict=True)):
            if (command.get("index") != index or command.get("status") != "complete"
                    or command.get("returncode") != 0 or command.get("direct_child_reaped") is not True
                    or len(command.get("outputs", [])) != len(expected["outputs"])):
                raise BuildDependencyError("execution_report")
            if version4:
                from tools.static_python_rsi_fixture.podman_custody import (
                    validate_custody_observation_v2,
                    validate_custody_observation_v3,
                    validate_custody_observation_v4,
                    validate_custody_observation_v5,
                )
                validate_observation = (validate_custody_observation_v5 if vfs_lifetime else
                                        validate_custody_observation_v4 if vfs_retained else
                                        validate_custody_observation_v3 if vfs_roots
                                        else validate_custody_observation_v2)
                validate_observation(
                    command, expected, planned["stage"], index, report.recipe_sha256,
                    recipe["environment"], inputs=recipe["inputs"], prior=prior,
                    workspace=workspace.absolute(), checkpoint=checkpoint,
                )
            elif custody_backend is not None:
                from tools.static_python_rsi_fixture.podman_custody import (
                    validate_custody_observation,
                )
                validate_custody_observation(command, expected, planned["stage"], index,
                                             report.recipe_sha256, recipe["environment"], custody_backend)
            elif "custody" in command:
                raise BuildDependencyError("unexpected_custody")
            for record, declared in zip(command["outputs"], expected["outputs"], strict=True):
                if (set(record) != {"path", "size", "sha256", "executable"}
                        or record["path"] != declared["path"] or type(record["size"]) is not int
                        or not 0 <= record["size"] <= declared["max_size"]
                        or record["executable"] is not declared["executable"]
                        or type(record["sha256"]) is not str or len(record["sha256"]) != 64
                        or any(char not in "0123456789abcdef" for char in record["sha256"])):
                    raise BuildDependencyError("execution_report")
                group.append(record)
                prior.append(record)
        if group != stage.get("outputs"):
            raise BuildDependencyError("execution_report")
        records.extend(group)
    payload = {
        "schema": ("lunar-static-python-build-execution-report-v7" if vfs_lifetime else
                   "lunar-static-python-build-execution-report-v6" if vfs_retained else
                   "lunar-static-python-build-execution-report-v5" if vfs_roots else
                   "lunar-static-python-build-execution-report-v4" if version4
                   else "lunar-static-python-build-execution-report-v3"),
        "recipe_sha256": report.recipe_sha256, "completed_stages": list(report.completed_stages),
        "stage_evidence": stages, "status": report.status, "reason": report.reason,
        "configured_closure_verified": False, "installation_accepted": False,
        "runtime_execution_performed": False, "production_admission": False,
    }
    if version4:
        payload.update(input_projection=INPUT_PROJECTION_V4,
                       immutable_custody_verified=False, driver_inputs_verified=False,
                       implicit_link_inputs_verified=False, online_publication=False)
    if vfs_roots:
        payload["custody_backend"] = source_data_backend
    return canonical(payload), sorted(records, key=lambda row: row["path"])


def _write_once(root: Path, name: str, raw: bytes, checkpoint: Callable[[], None]) -> str:
    """Retain only fixed create-only evidence names; never replace a failure."""
    checkpoint()
    current = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=current)
            os.close(current)
            current = child
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=current)
        try:
            view = memoryview(raw)
            while view:
                checkpoint()
                count = os.write(fd, view)
                if count <= 0:
                    raise BuildDependencyError("evidence_write")
                view = view[count:]
            os.fsync(fd)
            checkpoint()
        finally:
            os.close(fd)
    finally:
        os.close(current)
    return hashlib.sha256(raw).hexdigest()


def _run_dependency_checked_build(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str | None = None,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
    version4: bool = False,
    vfs_roots: bool = False,
    vfs_retained: bool = False,
    vfs_lifetime: bool = False,
    source_directories: bool = False,
) -> DependencyCheckedBuild:
    """Execute once and consume actual outputs under the original absolute budget.

    This is opt-in trusted-tool execution, not an isolation mechanism. In
    particular, depfiles cannot demonstrate all compiler-driver reads, and Zig
    cache products absent from earlier declared outputs are refused. No supplied
    output inventory, callback-produced receipt, current digest as authority,
    retry, default CLI fallback or extra execution budget is accepted.
    """
    source_data_backend = ("podman-snapshots-source-data-vfs-lifetime-v1" if vfs_lifetime else
                           "podman-snapshots-source-data-vfs-retained-v1" if vfs_retained else
                           "podman-snapshots-source-data-vfs-v1" if vfs_roots
                           else "podman-snapshots-source-data-v2")
    if (type(source_directories) is not bool
            or source_directories and not (version4 and vfs_roots and vfs_retained)):
        raise BuildDependencyError("dependency_path_profile")
    if (type(vfs_roots) is not bool or vfs_roots and not version4
            or type(vfs_retained) is not bool or vfs_retained and not (version4 and vfs_roots)
            or type(vfs_lifetime) is not bool
            or vfs_lifetime and not (version4 and vfs_roots and vfs_retained and source_directories)):
        raise BuildDependencyError("custody_backend")
    if not version4 and (zig_lld_profile_bytes is not None or expected_zig_lld_profile_sha256 is not None):
        raise BuildDependencyError("recipe_profile")
    if version4 and (type(custody_backend) is not str or custody_backend != source_data_backend):
        raise BuildDependencyError("custody_backend")
    validate_plan = (validate_dependency_capture_plan_v4 if version4
                     else validate_dependency_capture_plan)
    recipe, compiler_paths, linker_paths = validate_plan(
        recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        **({"zig_lld_profile_bytes": zig_lld_profile_bytes,
            "expected_zig_lld_profile_sha256": expected_zig_lld_profile_sha256} if version4 else {}),
    )
    (validate_dependency_command_graph_v4 if version4 else validate_dependency_command_graph)(recipe)
    if not version4 and custody_backend is not None and (type(custody_backend) is not str
            or custody_backend not in {"podman", "podman-snapshots-v1"}):
        raise BuildDependencyError("custody_backend")
    if (not _finite(deadline) or deadline <= 0
            or not callable(monotonic) or (interrupted is not None and not callable(interrupted))):
        raise BuildDependencyError("control")

    def checkpoint():
        failed = False
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
            failed = not _finite(now) or type(stop) is not bool
        except Exception:  # noqa: BLE001 - callbacks cannot leak paths or caller material
            failed = True
        if failed:
            raise BuildDependencyError("control")
        if stop:
            raise BuildDependencyError("interrupted")
        if now >= deadline:
            raise BuildDependencyError("deadline_expired")

    checkpoint()
    report = None
    failure = None
    try:
        if standalone_profile_bytes is not None:
            verify_standalone_linker_input(
                standalone_profile_bytes, expected_profile_sha256=expected_standalone_profile_sha256,
                toolchain_root=toolchain_root, checkpoint=checkpoint,
            )
        if zig_lld_profile_bytes is not None:
            verify_zig_lld_linker_input(
                zig_lld_profile_bytes, expected_profile_sha256=expected_zig_lld_profile_sha256,
                toolchain_root=toolchain_root, checkpoint=checkpoint,
            )
        runner = (run_pinned_build_v4_vfs_lifetime if vfs_lifetime else
                  run_pinned_build_v4_vfs_retained if vfs_retained else
                  run_pinned_build_v4_vfs if vfs_roots else
                  run_pinned_build_v4 if version4 else run_pinned_build_v3)
        report = runner(
            preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            source_root=source_root, toolchain_root=toolchain_root, workspace=workspace,
            deadline=deadline, interrupted=interrupted, monotonic=monotonic,
            **({} if custody_backend is None else {"custody_backend": custody_backend}),
        )
        checkpoint()
        report_bytes, outputs = _report_outputs(
            report, recipe, custody_backend, version4=version4, workspace=workspace, checkpoint=checkpoint,
            vfs_roots=vfs_roots, vfs_retained=vfs_retained,
            **({"vfs_lifetime": True} if vfs_lifetime else {}),
        )
        workspace = workspace.absolute()
        report_pin = {"path": "report.json", "size": len(report_bytes),
                      "sha256": hashlib.sha256(report_bytes).hexdigest(), "executable": False}
        _read_pin(workspace, report_pin, checkpoint)
        locations = {"source": workspace / "source", "toolchain": workspace / "toolchain",
                     "work": workspace / "work"}

        def verify_inputs():
            for role in ("source", "toolchain"):
                for record in recipe["inputs"][role]:
                    _read_pin(locations[role], record, checkpoint)
                    _read_pin((source_root if role == "source" else toolchain_root).absolute(),
                              record, checkpoint)

        verify_inputs()
        retained = {}
        captures = set(compiler_paths + linker_paths)
        for record in outputs:
            raw = _read_pin(locations["work"], record, checkpoint, retain=record["path"] in captures)
            if record["path"] in captures:
                retained[record["path"]] = raw
        inventory = canonical(outputs)
        inventory_sha = hashlib.sha256(inventory).hexdigest()
        roots = {role + "_root": str(path) for role, path in locations.items()}
        if custody_backend is not None:
            from tools.static_python_rsi_fixture.podman_custody import (
                GUEST_CURRENT_ROOT,
                GUEST_PRIOR_ROOT,
                GUEST_SOURCE_ROOT,
                GUEST_TOOLCHAIN_ROOT,
            )
            roots = {"source_root": GUEST_SOURCE_ROOT, "toolchain_root": GUEST_TOOLCHAIN_ROOT,
                     "work_root": GUEST_PRIOR_ROOT, "current_output_root": GUEST_CURRENT_ROOT}
        compare_compiler = (compare_compiler_dependencies_v4_source_directories if source_directories else
                            compare_compiler_dependencies_v4 if version4 else compare_compiler_dependencies)
        compiler = compare_compiler(
            recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            output_inventory_bytes=inventory, expected_output_inventory_sha256=inventory_sha,
            dependency_artifacts={path: retained[path] for path in compiler_paths}, **roots,
            **({"manifest_bytes": manifest_bytes, "expected_manifest_sha256": expected_manifest_sha256,
                "standalone_profile_bytes": standalone_profile_bytes,
                "expected_standalone_profile_sha256": expected_standalone_profile_sha256,
                "zig_lld_profile_bytes": zig_lld_profile_bytes,
                "expected_zig_lld_profile_sha256": expected_zig_lld_profile_sha256} if version4 else {}),
        )
        compare_linker = compare_linker_dependencies_v4 if version4 else compare_linker_dependencies
        linker = compare_linker(
            recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
            standalone_profile_bytes=standalone_profile_bytes,
            expected_standalone_profile_sha256=expected_standalone_profile_sha256,
            **({"zig_lld_profile_bytes": zig_lld_profile_bytes,
                "expected_zig_lld_profile_sha256": expected_zig_lld_profile_sha256} if version4 else {}),
            output_inventory_bytes=inventory, expected_output_inventory_sha256=inventory_sha,
            dependency_artifacts={path: retained[path] for path in linker_paths}, **roots,
        )
        checkpoint()
        verify_inputs()
        for record in outputs:
            _read_pin(locations["work"], record, checkpoint)
        _read_pin(workspace, report_pin, checkpoint)
        inventory_sha = _write_once(workspace, "dependency-output-inventory.json", inventory, checkpoint)
        compiler_sha = _write_once(workspace, "compiler-dependency-comparison.json",
                                   compiler.canonical_bytes, checkpoint)
        linker_sha = _write_once(workspace, "linker-dependency-comparison.json",
                                 linker.canonical_bytes, checkpoint)
        evidence = canonical({
            "schema": ("lunar-actual-build-dependency-consumer-v6" if vfs_lifetime else
                       "lunar-actual-build-dependency-consumer-v5" if source_directories else
                       "lunar-actual-build-dependency-consumer-v4" if vfs_retained else
                       "lunar-actual-build-dependency-consumer-v3" if vfs_roots else
                       "lunar-actual-build-dependency-consumer-v2" if version4
                       else "lunar-actual-build-dependency-consumer-v1"), "status": "compared",
            **({"custody_backend": source_data_backend} if vfs_roots else {}),
            **({"dependency_path_profile": SOURCE_DIRECTORY_PROFILE} if source_directories else {}),
            **({"input_projection": INPUT_PROJECTION_V4,
                "inputs_sha256": hashlib.sha256(canonical(recipe["inputs"])).hexdigest()} if version4 else {}),
            "recipe_sha256": expected_recipe_sha256, "manifest_sha256": expected_manifest_sha256,
            "execution_report_sha256": report_pin["sha256"],
            "output_inventory_sha256": inventory_sha,
            "compiler_comparison_sha256": compiler_sha, "linker_comparison_sha256": linker_sha,
            "compilations": len(compiler_paths), "links": len(linker_paths),
            "immutable_custody_verified": False, "driver_inputs_verified": False,
            "implicit_link_inputs_verified": False, "configured_closure_verified": False,
            "installation_accepted": False, "production_admission": False, "online_publication": False,
        })
        evidence_sha = _write_once(workspace, "dependency-report.json", evidence, checkpoint)
        return DependencyCheckedBuild(report, evidence_sha, compiler_sha, linker_sha, inventory_sha)
    except BuildExecutionError as exc:
        report, failure = exc.report, "execution_failed"
    except BuildDependencyError as exc:
        failure = exc.code.removeprefix("build_dependency_")
    except (CompilerDependencyError, LinkDependencyError):
        failure = "dependency_refused"
    except KeyboardInterrupt:
        failure = "interrupted"
    except Exception:  # noqa: BLE001 - retain original workspace without raw paths in refusal
        failure = "readback_or_evidence_failure"
    raise BuildDependencyError(failure, execution_report=report) from None


def run_dependency_checked_build(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str | None = None,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Consume the unchanged v3 runner, capture plan and persisted evidence."""
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
    )


def run_dependency_checked_build_v4(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-v2",
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Consume v4 actual source-data view evidence under the original budget.

    Only the explicit source-data Podman snapshot backend is accepted. This uses
    the original runner and consumer lifecycle and adds no retry or fallback.
    Detached observations, depfiles and readbacks grant no build/runtime authority.
    """
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        version4=True,
    )


def run_dependency_checked_build_v4_vfs(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-vfs-v1",
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Consume the explicit VFS root observation and exact persisted report.

    Recipe-v4 input and dependency contracts stay unchanged. No original v4
    report, alternate backend, detached root or extra attempt is accepted.
    """
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        version4=True, vfs_roots=True,
    )


def run_dependency_checked_build_v4_vfs_retained(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-vfs-retained-v1",
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Consume original retained VFS snapshots and the exact persisted report.

    Existing profile reports are refused. Snapshot readback, compiler depfiles
    and linker comparisons share the original deadline and confer no authority.
    """
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        version4=True, vfs_roots=True, vfs_retained=True,
    )


def run_dependency_checked_build_v4_vfs_retained_source_directories(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-vfs-retained-v1",
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Select finite source-directory comparisons on the original retained run.

    The original runner, report, readback, controls and linker gate are unchanged.
    Only this explicit entry point selects source-inventory-directories-v1; no
    old failed report is promoted and no retry or extra deadline is introduced.
    """
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        version4=True, vfs_roots=True, vfs_retained=True, source_directories=True,
    )


def run_dependency_checked_build_v4_vfs_lifetime_source_directories(
    preparation: RSIProfilePreparation, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    source_root: Path, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    custody_backend: str = "podman-snapshots-source-data-vfs-lifetime-v1",
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> DependencyCheckedBuild:
    """Consume the original report-v7 and finite VFS lifetime observations.

    This explicit profile uses the existing source-inventory directory comparison
    under the original execution budget. Old retained histories remain separate.
    """
    return _run_dependency_checked_build(
        preparation, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        source_root=source_root, toolchain_root=toolchain_root, workspace=workspace, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic, custody_backend=custody_backend,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        version4=True, vfs_roots=True, vfs_retained=True, vfs_lifetime=True, source_directories=True,
    )
