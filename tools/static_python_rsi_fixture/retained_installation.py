"""Read retained outputs into a candidate description, never accepted authority.

No receipt of build-source consumption is created. Original comparison files
are pinned historical attachments; present readback and self-consistency cannot
establish immutable custody, a live owner or installation acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lunar_evolution import static_python_fixed_profile as fixed
from lunar_evolution.static_python_installation import _CONFIG, _PRECONFIG
from tools.static_python_rsi_fixture.build_dependency_consumer import (
    DependencyCheckedBuild,
    _read_pin,
    _report_outputs,
    _signature,
)
from tools.static_python_rsi_fixture.dependency_capture import SOURCE_DIRECTORY_PROFILE
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    BuildExecutionReport,
    _open_beneath,
    _recipe,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical

_BACKEND = "podman-snapshots-source-data-vfs-retained-v1"
_LIFETIME_BACKEND = "podman-snapshots-source-data-vfs-lifetime-v1"
_WORKER_INPUT_BACKEND = "podman-snapshots-source-data-vfs-worker-input-view-v1"
_MAX_WIRE = 16 * 1024 * 1024
_FALSE = (
    "immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
    "configured_closure_verified", "installation_accepted", "production_admission", "online_publication",
)
_BUILD_FALSE = tuple(name for name in _FALSE if name != "configured_closure_verified")


class RetainedInstallationDescriptionError(ValueError):
    """Bounded refusal without paths, caller data or retained exception context."""

    def __init__(self, reason: str) -> None:
        self.code = "retained_installation_description_" + reason
        super().__init__(self.code)


class _Refusal(ValueError):
    pass


def _fail(reason: str) -> None:
    raise _Refusal(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pin(value: object) -> str:
    if (type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            or value in {"0" * 64, "f" * 64}):
        _fail("pin")
    return value


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            _fail("historical_json")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _fail("historical_json")


def _json(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 500_000 or depth > 24:
            _fail("historical_json")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in {str, int, bool, type(None)}:
            _fail("historical_json")
    if type(value) is not dict or canonical(value) != raw:
        _fail("historical_json")
    return value


def _read(root: Path, path: str, digest: str, checkpoint: Callable[[], None],
          *, maximum: int = _MAX_WIRE, executable: bool = False) -> tuple[bytes, int]:
    """Read and mode-observe one original held FD, then recheck its path binding."""
    checkpoint()
    fd = _open_beneath(root, path)
    try:
        checkpoint()
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum
                or bool(before.st_mode & 0o111) is not executable):
            _fail("file")
        chunks, received = [], 0
        while True:
            checkpoint()
            block = os.read(fd, 65536)
            checkpoint()
            if not block:
                break
            received += len(block)
            if received > before.st_size:
                _fail("file")
            chunks.append(block)
        raw = b"".join(chunks)
        if (received != before.st_size or _sha(raw) != digest
                or _signature(os.fstat(fd)) != _signature(before)):
            _fail("file")
        checkpoint()
        again = _open_beneath(root, path)
        try:
            if _signature(os.fstat(again)) != _signature(before):
                _fail("file")
        finally:
            os.close(again)
        checkpoint()
        return raw, stat.S_IMODE(before.st_mode)
    finally:
        os.close(fd)


def _record(row: dict) -> dict:
    return {key: row[key] for key in ("path", "size", "sha256")}


@dataclass(frozen=True, slots=True)
class RetainedFixedInstallationDescription:
    """Candidate bytes and historical bindings; construction grants no authority."""

    candidate_bytes: bytes
    runtime_closure: bytes
    recipe_sha256: str
    dependency_report_sha256: str
    output_inventory_sha256: str
    cpython_inventory_sha256: str
    augmented_source_inventory_sha256: str

    @property
    def sha256(self) -> str:
        return _sha(self.candidate_bytes)

    @property
    def production_admission(self) -> bool:
        return False

    @property
    def online_publication(self) -> bool:
        return False

    def to_dict(self) -> dict:
        return json.loads(self.candidate_bytes)


def _prepare(
    build: DependencyCheckedBuild, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    expected_manifest_sha256: str, expected_dependency_report_sha256: str,
    runtime_closure: bytes, expected_runtime_closure_sha256: str,
    expected_cpython_inventory_sha256: str, expected_augmented_source_inventory_sha256: str,
    installation_version: str, workspace: Path, deadline: float,
    monotonic: Callable[[], float], interrupted: Callable[[], bool] | None,
    lifetime: bool = False,
    worker_input_view: bool = False,
) -> RetainedFixedInstallationDescription:
    if (type(lifetime) is not bool or type(worker_input_view) is not bool
            or worker_input_view and not lifetime):
        _fail("history_profile")
    backend = _WORKER_INPUT_BACKEND if worker_input_view else _LIFETIME_BACKEND if lifetime else _BACKEND
    for value, maximum in ((recipe_bytes, _MAX_WIRE),
                           (runtime_closure, fixed.MAX_FIXED_CLOSURE_BYTES)):
        if type(value) is not bytes or not 0 < len(value) <= maximum:
            _fail("raw")
    for value in (expected_recipe_sha256, expected_manifest_sha256,
                  expected_dependency_report_sha256, expected_runtime_closure_sha256,
                  expected_cpython_inventory_sha256, expected_augmented_source_inventory_sha256):
        _pin(value)
    if (type(build) is not DependencyCheckedBuild
            or type(build.execution_report) is not BuildExecutionReport
            or any(getattr(build, name) is not False for name in _BUILD_FALSE)):
        _fail("build")
    for value in (build.evidence_sha256, build.compiler_comparison_sha256,
                  build.linker_comparison_sha256, build.output_inventory_sha256):
        _pin(value)
    if build.evidence_sha256 != expected_dependency_report_sha256:
        _fail("dependency_report")
    if (type(installation_version) is not str
            or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", installation_version) is None
            or type(workspace) not in {Path, type(Path())}):
        _fail("input")
    if (type(deadline) not in {int, float} or not math.isfinite(deadline) or deadline <= 0
            or not callable(monotonic) or interrupted is not None and not callable(interrupted)):
        _fail("control")

    def checkpoint():
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
        except Exception:  # noqa: BLE001 - fixed callback refusal without caller material
            _fail("control")
        if type(now) not in {int, float} or not math.isfinite(now) or type(stop) is not bool:
            _fail("control")
        if stop:
            _fail("interrupted")
        if now >= deadline:
            _fail("deadline")

    checkpoint()
    recipe = _recipe(recipe_bytes, expected_recipe_sha256, version4=True)
    if _sha(canonical(recipe["inputs"]["source"])) != expected_augmented_source_inventory_sha256:
        _fail("augmented_source_inventory")
    if _sha(runtime_closure) != expected_runtime_closure_sha256:
        _fail("runtime_closure")
    closure = _json(runtime_closure)
    if closure.get("cpython_inventory_sha256") != expected_cpython_inventory_sha256:
        _fail("cpython_inventory")
    root = workspace.absolute()
    report_bytes, outputs = _report_outputs(
        build.execution_report, recipe, backend, version4=True, workspace=root,
        checkpoint=checkpoint, vfs_roots=True, vfs_retained=True,
        **({"vfs_lifetime": True} if lifetime else {}),
        **({"vfs_worker_input_view": True} if worker_input_view else {}),
    )
    inventory = canonical(outputs)
    if _sha(inventory) != build.output_inventory_sha256:
        _fail("output_inventory")
    inputs_pin = _sha(canonical(recipe["inputs"]))
    common = {
        "recipe_sha256": expected_recipe_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "output_inventory_sha256": build.output_inventory_sha256,
        "input_projection": INPUT_PROJECTION_V4, "inputs_sha256": inputs_pin,
    }
    historical = {
        "report.json": _sha(report_bytes),
        "dependency-output-inventory.json": build.output_inventory_sha256,
        "dependency-report.json": expected_dependency_report_sha256,
        "compiler-dependency-comparison.json": build.compiler_comparison_sha256,
        "linker-dependency-comparison.json": build.linker_comparison_sha256,
    }
    history_bytes = {name: _read(root, name, pin, checkpoint)[0] for name, pin in historical.items()}
    if history_bytes["report.json"] != report_bytes or history_bytes["dependency-output-inventory.json"] != inventory:
        _fail("historical_binding")
    dependency = _json(history_bytes["dependency-report.json"])
    expected_dependency = {
        "schema": "lunar-actual-build-dependency-consumer-v7" if worker_input_view else
                  "lunar-actual-build-dependency-consumer-v6" if lifetime else
                  "lunar-actual-build-dependency-consumer-v5", "status": "compared",
        "custody_backend": backend, "dependency_path_profile": SOURCE_DIRECTORY_PROFILE,
        **common, "execution_report_sha256": historical["report.json"],
        "compiler_comparison_sha256": build.compiler_comparison_sha256,
        "linker_comparison_sha256": build.linker_comparison_sha256,
        "compilations": dependency.get("compilations"), "links": dependency.get("links"),
        **dict.fromkeys(_FALSE, False),
    }
    if (dependency != expected_dependency or any(dependency.get(name) is not False for name in _FALSE)
            or any(type(dependency.get(name)) is not int or not 0 < dependency[name] <= 1024
                   for name in ("compilations", "links"))):
        _fail("dependency_report")
    for name, schema, vector in (
        ("compiler-dependency-comparison.json", "lunar-cpython-compiler-dependency-comparison-v3", "compilations"),
        ("linker-dependency-comparison.json", "lunar-cpython-linker-dependency-comparison-v2", "links"),
    ):
        compared = _json(history_bytes[name])
        if (compared.get("schema") != schema
                or any(compared.get(key) != value for key, value in common.items())
                or any(compared.get(key) is not False for key in _FALSE)
                or type(compared.get(vector)) is not list
                or len(compared[vector]) != dependency[vector]
                or vector == "compilations" and compared.get("dependency_path_profile") != SOURCE_DIRECTORY_PROFILE):
            _fail("comparison")

    source_rows = {row["path"]: row for row in recipe["inputs"]["source"]}
    output_rows = {row["path"]: row for row in outputs}
    if len(output_rows) != len(outputs):
        _fail("output_inventory")

    def source_record(row):
        path = row["path"]
        if path not in source_rows or _record(source_rows[path]) != row:
            _fail("source")
        return row.copy()

    def generated(path):
        row = output_rows.get(path)
        if row is None or row["size"] <= 0 or row["executable"] is not False:
            _fail("generated")
        return _record(row)

    if (type(closure.get("sources")) is not list or len(closure["sources"]) > 512
            or type(closure.get("frozen")) is not list or not 0 < len(closure["frozen"]) <= 256
            or type(closure.get("native_units")) is not list or len(closure["native_units"]) > 128):
        _fail("runtime_closure")
    for row in closure["sources"]:
        source_record(row)
    frozen = [{
        "name": unit["name"], "generator_id": unit["generator_id"], "package": unit["package"],
        "source": source_record({"path": unit["source"], "size": unit["source_size"],
                                 "sha256": unit["source_sha256"]}),
        "generated": generated(unit["output"]),
    } for unit in closure["frozen"]]
    native = [{
        "module": unit["module"],
        "source": source_record({"path": unit["source"], "size": unit["source_size"],
                                 "sha256": unit["source_sha256"]}),
        "object": generated("objects/" + unit["object"]), "extra_flags": unit["extra_flags"],
    } for unit in closure["native_units"]]
    config = source_rows.get("configuration/pyconfig.h")
    solver = closure.get("solver")
    if solver not in {"openevolve", "shinka"} or config is None or config["executable"] is not False:
        _fail("profile")
    image = output_rows.get("bin/lunar-" + solver)
    if image is None or image["executable"] is not True or image["size"] <= 0:
        _fail("image")

    def readback():
        for role in ("source", "toolchain"):
            for row in recipe["inputs"][role]:
                _read_pin(root / role, row, checkpoint)
        for row in outputs:
            _read_pin(root / "work", row, checkpoint)
        closure_row = source_rows.get("runtime/closure.json")
        if (closure_row is None
                or _read_pin(root / "source", closure_row, checkpoint, retain=True) != runtime_closure):
            _fail("runtime_closure")

    readback()
    image_raw, mode = _read(root / "work", image["path"], image["sha256"], checkpoint,
                            maximum=128 * 1024 * 1024, executable=True)
    candidate = {
        "schema": fixed.FIXED_INSTALLATION_SCHEMA, "profile_version": "fixed-" + solver + "-v1",
        "installation_version": installation_version,
        "runtime_closure_sha256": expected_runtime_closure_sha256,
        "source_inventory_sha256": expected_cpython_inventory_sha256,
        "configuration": _record(config), "image": {**_record(image), "mode": mode},
        "frozen_modules": frozen, "native_units": native,
        "initialization": {"preconfig": _PRECONFIG.copy(), "config": _CONFIG.copy()},
        "claims": dict.fromkeys(fixed._CLAIMS, False),
    }
    raw = fixed._canonical(candidate)
    # These DERIVED pins are only an internal schema/self-consistency check.
    # The result is never returned as an independently approved installation.
    checked = fixed.parse_fixed_python_installation(
        raw, runtime_closure=runtime_closure, expected_installation_sha256=_sha(raw),
        expected_installation_version=installation_version,
        expected_runtime_closure_sha256=expected_runtime_closure_sha256,
        expected_source_inventory_sha256=expected_cpython_inventory_sha256,
        expected_configuration_sha256=config["sha256"], expected_artifact_sha256=image["sha256"],
        expected_frozen_inventory_sha256=_sha(fixed._canonical(frozen)),
        expected_native_inventory_sha256=_sha(fixed._canonical(native)),
    )
    fixed.verify_fixed_python_image(checked, image_raw, expected_installation_sha256=_sha(raw))
    checkpoint()
    readback()
    for name, pin in historical.items():
        if _read(root, name, pin, checkpoint)[0] != history_bytes[name]:
            _fail("historical_binding")
    if _read(root / "work", image["path"], image["sha256"], checkpoint,
             maximum=128 * 1024 * 1024, executable=True)[1] != mode:
        _fail("image")
    checkpoint()
    return RetainedFixedInstallationDescription(
        raw, runtime_closure, expected_recipe_sha256, expected_dependency_report_sha256,
        build.output_inventory_sha256, expected_cpython_inventory_sha256,
        expected_augmented_source_inventory_sha256,
    )


def prepare_retained_fixed_installation_description(
    build: DependencyCheckedBuild, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    expected_manifest_sha256: str, expected_dependency_report_sha256: str,
    runtime_closure: bytes, expected_runtime_closure_sha256: str,
    expected_cpython_inventory_sha256: str, expected_augmented_source_inventory_sha256: str,
    installation_version: str, workspace: Path, deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    interrupted: Callable[[], bool] | None = None,
) -> RetainedFixedInstallationDescription:
    """Read retained history once under its deadline; emit only candidate bytes."""
    try:
        return _prepare(
            build, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_dependency_report_sha256=expected_dependency_report_sha256,
            runtime_closure=runtime_closure, expected_runtime_closure_sha256=expected_runtime_closure_sha256,
            expected_cpython_inventory_sha256=expected_cpython_inventory_sha256,
            expected_augmented_source_inventory_sha256=expected_augmented_source_inventory_sha256,
            installation_version=installation_version, workspace=workspace, deadline=deadline,
            monotonic=monotonic, interrupted=interrupted,
        )
    except _Refusal as exc:
        reason = str(exc)
    except Exception:  # noqa: BLE001 - external validators, IO and callbacks retain no private material
        reason = "readback_or_description"
    raise RetainedInstallationDescriptionError(reason) from None


def prepare_lifetime_fixed_installation_description(
    build: DependencyCheckedBuild, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    expected_manifest_sha256: str, expected_dependency_report_sha256: str,
    runtime_closure: bytes, expected_runtime_closure_sha256: str,
    expected_cpython_inventory_sha256: str, expected_augmented_source_inventory_sha256: str,
    installation_version: str, workspace: Path, deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    interrupted: Callable[[], bool] | None = None,
) -> RetainedFixedInstallationDescription:
    """Read only lifetime-v7/v6 history into unaccepted candidate bytes.

    Original retained histories belong to the separate retained entry point.
    The lifetime observations confer no immutable-input or runtime authority.
    """
    try:
        return _prepare(
            build, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_dependency_report_sha256=expected_dependency_report_sha256,
            runtime_closure=runtime_closure, expected_runtime_closure_sha256=expected_runtime_closure_sha256,
            expected_cpython_inventory_sha256=expected_cpython_inventory_sha256,
            expected_augmented_source_inventory_sha256=expected_augmented_source_inventory_sha256,
            installation_version=installation_version, workspace=workspace, deadline=deadline,
            monotonic=monotonic, interrupted=interrupted, lifetime=True,
        )
    except _Refusal as exc:
        reason = str(exc)
    except Exception:  # noqa: BLE001 - external validators, IO and callbacks retain no private material
        reason = "readback_or_description"
    raise RetainedInstallationDescriptionError(reason) from None


def prepare_worker_input_view_fixed_installation_description(
    build: DependencyCheckedBuild, *, recipe_bytes: bytes, expected_recipe_sha256: str,
    expected_manifest_sha256: str, expected_dependency_report_sha256: str,
    runtime_closure: bytes, expected_runtime_closure_sha256: str,
    expected_cpython_inventory_sha256: str, expected_augmented_source_inventory_sha256: str,
    installation_version: str, workspace: Path, deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    interrupted: Callable[[], bool] | None = None,
) -> RetainedFixedInstallationDescription:
    """Read worker-view v8/v7 history into the existing unaccepted candidate.

    Original summary/control validation and bounded readbacks remain mandatory.
    A finite input view does not confer immutable custody or runtime authority.
    """
    try:
        return _prepare(
            build, recipe_bytes=recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_dependency_report_sha256=expected_dependency_report_sha256,
            runtime_closure=runtime_closure, expected_runtime_closure_sha256=expected_runtime_closure_sha256,
            expected_cpython_inventory_sha256=expected_cpython_inventory_sha256,
            expected_augmented_source_inventory_sha256=expected_augmented_source_inventory_sha256,
            installation_version=installation_version, workspace=workspace, deadline=deadline,
            monotonic=monotonic, interrupted=interrupted, lifetime=True, worker_input_view=True,
        )
    except _Refusal as exc:
        reason = str(exc)
    except Exception:  # noqa: BLE001 - preserve bounded refusal without historical private material
        reason = "readback_or_description"
    raise RetainedInstallationDescriptionError(reason) from None
